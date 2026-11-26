#!/usr/bin/env -S uv run -q python
"""Publish apps to the catalog the boards install from (Settings > Apps > Get apps): GitHub Releases.

    tools/apps/publish.py [--key KEY] [--repo OWNER/NAME] [--base [--images DIR]] [NAME ...]
    e.g. tools/apps/publish.py system countdown castle cruise
         tools/apps/publish.py --base castle          (a base system update, and an app, together)

For each app: pack and sign it (tools/apps/pack.py: OpenSSL asks for the key's passphrase once; KEY
default ~/.config/licheepi-nano/module-signing.pem), and make a release ID-VERSION with its tarball and
.sig (a version that's already published is refused: bump app.json's version). Then the catalog: the
release "catalog" holds catalog.json, one entry per app (its latest version: id, name, version, api,
runtime, size, url, sig), and catalog.json.sig, the catalog signed the way an app is (so the board checks
it with modinstall too). REPO default: this repository's GitHub remote (origin).

--base: the base system too (tools/apps/pack.py --base, from DIR, default build/images-wifi): a release
base-VERSION with its .img.gz and .sig (VERSION: board/licheepi_nano/VERSION when it was built; already
published is refused), and the catalog's "base" entry (version, board, size, url, sig): Settings > Apps >
Get apps on a board shows it as Base system, Update.

Needs the GitHub CLI, once: brew install gh; gh auth login.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import layout, pack

DEFAULT_KEY = os.path.expanduser("~/.config/licheepi-nano/module-signing.pem")
CATALOG_TAG = "catalog"


def gh(*args, check=True, capture=True):
    r = subprocess.run(["gh", *args], capture_output=capture, text=True)
    if check and r.returncode: sys.exit("gh %s failed: %s" % (" ".join(args[:3]), (r.stderr or "").strip()[-400:]))
    return r


def github_repo():
    url = subprocess.run(["git", "-C", REPO, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", url)
    if not m: sys.exit("no GitHub remote (origin): --repo OWNER/NAME")
    return m.group(1)


def main():
    a = sys.argv[1:]
    def option(flag):
        if flag not in a: return None
        i = a.index(flag); v = a[i + 1]; del a[i:i + 2]; return v
    key = option("--key") or DEFAULT_KEY
    repo = option("--repo") or github_repo()
    images = option("--images") or os.path.join(REPO, "build", "images-wifi")
    with_base = "--base" in a
    if with_base: a.remove("--base")
    names = [x for x in a if not x.startswith("-")]
    if not (names or with_base) or len(names) != len(a): sys.exit(__doc__)
    base_version = None
    if with_base:
        vfile = os.path.join(images, "base-version")
        if not os.path.isfile(vfile): sys.exit("no base-version in %s: a build's output folder (tools/build/build.sh --wifi)?" % images)
        base_version = open(vfile).read().strip()
    if not shutil.which("gh"): sys.exit("needs the GitHub CLI: brew install gh; gh auth login")
    if gh("auth", "status", check=False).returncode: sys.exit("log the GitHub CLI in first: gh auth login")
    if not os.path.exists(key): sys.exit("no signing key at %s (tools/apps/keygen.sh)" % key)
    for n in names:
        if not os.path.isfile(os.path.join(REPO, "apps", n, "app.json")): sys.exit("no app %s in apps/" % n)
        m = layout.manifest(n)
        if gh("release", "view", "%s-%s" % (n, m["version"]), "-R", repo, check=False).returncode == 0:
            sys.exit("%s %s is already published: bump its version in apps/%s/app.json" % (n, m["version"], n))
    base_published = with_base and gh("release", "view", "base-%s" % base_version, "-R", repo, check=False).returncode == 0

    tmp = tempfile.mkdtemp(prefix="publish-")
    # the catalog as it is (if there is one yet)
    catalog = {"apps": []}
    if gh("release", "download", CATALOG_TAG, "-R", repo, "-p", "catalog.json", "-D", tmp, check=False).returncode == 0:
        try: catalog = json.load(open(os.path.join(tmp, "catalog.json")))
        except ValueError: pass

    for n in names:
        tar = pack.pack(n, key)
        meta = layout.manifest(n)
        tag = "%s-%s" % (n, meta["version"])
        gh("release", "create", tag, tar, tar + ".sig", "-R", repo, "--title", "%s %s" % (meta.get("name", n), meta["version"]),
           "--notes", "%s %s, signed (tools/apps/publish.py). Install it from the board: Settings > Apps > Get apps." %
           (meta.get("name", n), meta["version"]))
        dl = "https://github.com/%s/releases/download/%s/" % (repo, tag)
        entry = {"id": n, "name": meta.get("name", n), "version": meta["version"], "api": meta.get("api", 1),
                 "size": os.path.getsize(tar), "url": dl + os.path.basename(tar), "sig": dl + os.path.basename(tar) + ".sig"}
        if meta.get("runtime"): entry["runtime"] = meta["runtime"]
        if meta.get("kind"): entry["kind"] = meta["kind"]
        catalog["apps"] = [e for e in catalog.get("apps", []) if e.get("id") != n] + [entry]
        print("published %s" % tag)

    if with_base:
        tag = "base-%s" % base_version
        url = "https://github.com/%s/releases/download/%s/" % (repo, tag)
        name = "base-%s.img.gz" % base_version
        if base_published:                                # (already a release: the catalog points at it again)
            if (catalog.get("base") or {}).get("version") == base_version:
                sys.exit("base %s is already published, and in the catalog: bump board/licheepi_nano/VERSION and rebuild" % base_version)
            assets = json.loads(gh("release", "view", tag, "-R", repo, "--json", "assets").stdout)["assets"]
            size = next((x["size"] for x in assets if x["name"] == name), None)
            if size is None or not any(x["name"] == name + ".sig" for x in assets): sys.exit("release %s has no %s and .sig" % (tag, name))
            print("base %s: already a release, back in the catalog" % base_version)
        else:
            pkg, sig = pack.pack_base(images, key)
            gh("release", "create", tag, pkg, sig, "-R", repo, "--title", "Base system %s" % base_version,
               "--notes", "The base system %s for the %s, signed (tools/apps/publish.py --base). Install it from the board: "
               "Settings > Apps > Get apps > Base system." % (base_version, pack.BOARD))
            size = os.path.getsize(pkg)
            print("published %s" % tag)
        catalog["base"] = {"version": base_version, "board": pack.BOARD, "size": size, "url": url + name, "sig": url + name + ".sig"}

    catalog["apps"].sort(key=lambda e: e["id"])
    catalog["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = os.path.join(tmp, "catalog.json")
    with open(path, "w") as f: json.dump(catalog, f, indent=1)
    pack.sign(path, {"id": "catalog", "name": "App catalog", "version": time.strftime("%Y.%m.%d.%H%M%S", time.gmtime()), "api": 0}, key)
    if gh("release", "view", CATALOG_TAG, "-R", repo, check=False).returncode:
        gh("release", "create", CATALOG_TAG, "-R", repo, "--title", "App catalog",
           "--notes", "The catalog boards install apps from (catalog.json, signed: catalog.json.sig). Updated by tools/apps/publish.py.")
    gh("release", "upload", CATALOG_TAG, path, path + ".sig", "-R", repo, "--clobber")
    print("catalog: %d apps%s -> https://github.com/%s/releases/tag/%s" % (
        len(catalog["apps"]), ", base %s" % catalog["base"]["version"] if catalog.get("base") else "", repo, CATALOG_TAG))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
