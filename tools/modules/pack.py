#!/usr/bin/env python3
"""Pack a vacation-countdown module for publishing: a tarball of exactly what goes on the board, a
manifest of its files' SHA-256s, and (with a key) an Ed25519 signature.

    tools/modules/pack.py NAME [--key KEY.pem] [--themes "a b"]
    -> build/modules/NAME-VERSION.tar.gz (+ .sig with --key)

What goes in is what vacation/install.sh puts in /apps/vacation/modules/NAME: the module's folder,
except its scenes other than the default (and --themes), and only those scenes' *.gz and theme.json;
not its tools/ (desktop helpers), Python caches, or the map's desktop previews. files() below is that
rule; tools/test/check.py checks it against install.sh. The tarball is reproducible: files in order,
owned by root, timestamps 0. MANIFEST.json inside it: the module's id, name, version and api, and
each file's size and SHA-256.

Signing: an Ed25519 key (`openssl genpkey -algorithm ed25519 -out module-signing.pem`; keep it
private, out of the repository), and OpenSSL 1.1.1 or newer (not macOS's LibreSSL):
    openssl pkeyutl -sign -inkey KEY.pem -rawin -in NAME-VERSION.tar.gz -out NAME-VERSION.tar.gz.sig
which is what --key does. Its public half (`openssl pkey -in KEY.pem -pubout`) is what a board
would check with (`openssl pkeyutl -verify -pubin -inkey PUB.pem -rawin -in TAR -sigfile SIG`).
"""
import fnmatch, gzip, hashlib, io, json, os, subprocess, sys, tarfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODULES = os.path.join(REPO, "vacation", "modules")
SKIP_DIRS = {"tools", "__pycache__", ".git"}
SKIP_FILES = ["map/preview_*.png", "*.pyc", ".DS_Store"]


def files(name, themes=()):
    """The module's files that go on the board: [(path relative to the module, absolute path)], sorted."""
    root = os.path.join(MODULES, name)
    meta = json.load(open(os.path.join(root, "module.json")))
    sc = meta.get("scene", {}); sdir = sc.get("dir", "scenes")
    keep_scenes = {sc.get("default", "")} | set(themes)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        top = rel_dir.split(os.sep)[0]
        if top in SKIP_DIRS: dirnames[:] = []; continue
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            if any(fnmatch.fnmatch(rel, pat) for pat in SKIP_FILES): continue
            parts = rel.split(os.sep)
            if parts[0] == sdir:                       # scenes: the kept ones, and only what the device loads
                if len(parts) < 3 or parts[1] not in keep_scenes: continue
                if not (fn.endswith(".gz") or fn == "theme.json") or len(parts) > 3: continue
            out.append((rel, os.path.join(dirpath, fn)))
    return sorted(out), meta


def pack(name, key=None, themes=()):
    entries, meta = files(name, themes)
    manifest = {k: meta.get(k) for k in ("id", "name", "version", "api")}
    manifest["files"] = {rel: {"size": os.path.getsize(p), "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
                         for rel, p in entries}
    out_dir = os.path.join(REPO, "build", "modules"); os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s-%s.tar.gz" % (name, meta.get("version", "0")))
    def add(tar, arcname, data, mode):
        ti = tarfile.TarInfo(arcname); ti.size = len(data); ti.mode = mode; ti.mtime = 0
        ti.uid = ti.gid = 0; ti.uname = ti.gname = "root"; tar.addfile(ti, io.BytesIO(data))
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        add(tar, "%s/MANIFEST.json" % name, json.dumps(manifest, indent=1, sort_keys=True).encode(), 0o644)
        for rel, p in entries:
            add(tar, "%s/%s" % (name, rel), open(p, "rb").read(), 0o755 if os.access(p, os.X_OK) else 0o644)
    with open(out, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", compresslevel=9, mtime=0, filename="") as gz: gz.write(raw.getvalue())
    print("%s: %d files, %d bytes" % (os.path.relpath(out, REPO), len(entries), os.path.getsize(out)))
    if key:
        r = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", out, "-out", out + ".sig"],
                           capture_output=True, text=True)
        if r.returncode: sys.exit("signing failed (OpenSSL 1.1.1 or newer, an Ed25519 key?): " + r.stderr.strip())
        print("signed:", os.path.relpath(out + ".sig", REPO))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    key = a[a.index("--key") + 1] if "--key" in a else None
    themes = a[a.index("--themes") + 1].split() if "--themes" in a else ()
    pack(a[0], key, themes)
