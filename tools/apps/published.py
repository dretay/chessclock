#!/usr/bin/env -S uv run -q python
"""What's published, against what's here: for the Scene Builder's Publish (tools/preview/preview.py), or
by itself.

    tools/apps/published.py [NAME ...]        (default: every app)

For each app: its version here (app.json), the version in the catalog (the public catalog.json that
tools/apps/publish.py keeps on GitHub Releases), and whether its files have changed since that version
was published: the published package's MANIFEST.json (every file's SHA-256, tools/apps/pack.py) against
the files here. That manifest is downloaded once per version (the package, read as a stream) and kept
in build/published/. For an app laid out as it is (a countdown app), every file is compared; for one
with an install.sh (the system package, the countdown runtime), the files it copies as they are (its
compiled parts can't be compared without building them), and a new .py file counts as a change.
"""
import hashlib, json, os, re, subprocess, sys, tarfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import layout

CACHE = os.path.join(REPO, "build", "published")
_catalog = {}


def github_repo():
    url = subprocess.run(["git", "-C", REPO, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", url)
    return m.group(1) if m else None


def catalog_url(repo=None):
    repo = repo or github_repo()
    return repo and "https://github.com/%s/releases/download/catalog/catalog.json" % repo


def catalog(repo=None, max_age=60):
    """The published catalog ({} when there's none yet, or no network), kept for max_age seconds."""
    url = catalog_url(repo)
    if not url: return {}
    if url in _catalog and time.time() - _catalog[url][0] < max_age: return _catalog[url][1]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "licheepi-publish"})
        with urllib.request.urlopen(req, timeout=15) as r: data = json.load(r)
    except Exception:                                    # (404 before the first publish, offline, ...)
        data = {}
    _catalog[url] = (time.time(), data)
    return data


def vtuple(v):
    try: return tuple(int(x) for x in str(v).split("."))
    except ValueError: return (0,)


def next_version(v):
    parts = str(v).split(".")
    return ".".join(parts[:-1] + [str(int(parts[-1]) + 1)]) if parts and parts[-1].isdigit() else v


def published_manifest(entry):
    """The published package's MANIFEST.json ({"files": {rel: {"size", "sha256"}}}), or None."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s-%s.json" % (entry["id"], entry["version"]))
    if os.path.exists(path):
        try: return json.load(open(path))
        except ValueError: pass
    try:
        req = urllib.request.Request(entry["url"], headers={"User-Agent": "licheepi-publish"})
        with urllib.request.urlopen(req, timeout=60) as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
            for m in tar:
                if m.name == "%s/MANIFEST.json" % entry["id"]:
                    data = json.load(tar.extractfile(m)); break
            else: return None
    except Exception:
        return None
    json.dump(data, open(path, "w"), indent=1)
    return data


def sha256(path):
    with open(path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def same_but_version(path, want, published_version):
    """app.json against the published one's hash, its version taken as the published one's: a new version
    number alone isn't a change."""
    if not published_version: return False
    s = open(path).read()
    s = re.sub(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + published_version + m.group(2), s, count=1)
    return hashlib.sha256(s.encode()).hexdigest() == want


def changes(name, manifest):
    """The files that differ from the published manifest's: [(rel, "changed" | "new" | "gone")]. A new
    version in app.json alone doesn't count."""
    pub = (manifest or {}).get("files", {})
    pv = (manifest or {}).get("version")
    def differs(rel, path):
        want = pub[rel].get("sha256")
        if sha256(path) == want: return False
        return not (rel == "app.json" and same_but_version(path, want, pv))
    out = []
    if os.path.exists(os.path.join(layout.APPS, name, "install.sh")):
        root = os.path.join(layout.APPS, name)
        for rel, info in pub.items():
            here = os.path.join(root, rel)
            if os.path.isfile(here) and differs(rel, here): out.append((rel, "changed"))
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in layout.SKIP_DIRS]
            for f in fs:
                rel = os.path.relpath(os.path.join(d, f), root)
                if f.endswith(".py") and rel not in pub and not rel.startswith("tools/"): out.append((rel, "new"))
    else:
        here = dict(layout.files(name))
        for rel, p in here.items():
            if rel not in pub: out.append((rel, "new"))
            elif differs(rel, p): out.append((rel, "changed"))
        out += [(rel, "gone") for rel in pub if rel not in here and rel != "MANIFEST.json"]
    return sorted(out)


def status(name, cat=None):
    """{"id", "name", "version", "published", "changed": [...], "ready", "blocked", "next"} for an app:
    ready: its version here can be published (none yet, or newer than the published one); blocked: it
    has changes, and the same version as the published one (bump it first)."""
    m = layout.manifest(name)
    cat = catalog() if cat is None else cat
    entry = next((e for e in cat.get("apps", []) if e.get("id") == name), None)
    out = {"id": name, "name": m.get("name", name), "version": m.get("version", ""), "published": entry and entry.get("version"),
           "changed": [], "unknown": False}
    if entry:
        man = published_manifest(entry)
        if man is None: out["unknown"] = True
        else: out["changed"] = changes(name, man)
    newer = not entry or vtuple(out["version"]) > vtuple(entry.get("version"))
    out["ready"] = newer
    out["blocked"] = bool(entry) and not newer and bool(out["changed"])
    out["next"] = next_version(entry["version"]) if entry and not newer else None
    return out


def set_version(name, version):
    """Write VERSION into apps/NAME/app.json (its "version" line, the rest as it is)."""
    if not re.fullmatch(r"\d+(\.\d+)*", version or ""): raise ValueError("a version is numbers and dots: 1.2.3")
    p = os.path.join(layout.APPS, name, "app.json"); s = open(p).read()
    s2, n = re.subn(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + version + m.group(2), s, count=1)
    if not n: raise ValueError("no version in %s" % p)
    open(p, "w").write(s2)


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(n for n in os.listdir(layout.APPS) if os.path.isfile(os.path.join(layout.APPS, n, "app.json")))
    cat = catalog()
    for n in names:
        s = status(n, cat)
        what = ("%d files changed" % len(s["changed"])) if s["changed"] else ("?" if s["unknown"] else "unchanged")
        print("%-14s here %-8s published %-8s %s%s" % (n, s["version"], s["published"] or "-", what,
              "  (bump it: %s)" % s["next"] if s["blocked"] else "  ready to publish" if s["ready"] else ""))
