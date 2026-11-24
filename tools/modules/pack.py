#!/usr/bin/env python3
"""Pack a vacation-countdown module for publishing: a tarball of exactly what goes on the board, a
manifest of its files' SHA-256s, and (with a key) a signed statement for the board's modinstall.

    tools/modules/pack.py NAME [--key KEY.pem] [--themes "a b"]
    -> build/modules/NAME-VERSION.tar.gz (+ .sig with --key)

What goes in is what vacation/install.sh puts in /apps/vacation/modules/NAME: the module's folder,
except its scenes other than the default (and --themes), and only those scenes' *.gz and theme.json;
not its tools/ (desktop helpers), Python caches, or the map's desktop previews. files() below is that
rule; tools/test/check.py checks it against install.sh. The tarball is reproducible: files in order,
owned by root, timestamps 0. MANIFEST.json inside it: the module's id, name, version and api, and
each file's size and SHA-256.

Signing (--key): the Ed25519 key tools/modules/keygen.sh made, and OpenSSL 3.0 or newer (not
macOS's LibreSSL; OPENSSL picks one). The .sig is a short statement, signed: the module's id, name,
version and api, and the tarball's size and SHA-512 (the format: package/modinstall/src/modinstall.c).
The board checks it against the public keys in its /etc/modules/trusted.keys, then the tarball against
it: `modinstall NAME-VERSION.tar.gz`.
"""
import fnmatch, getpass, gzip, hashlib, io, json, os, subprocess, sys, tarfile, tempfile

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


OPENSSL = os.environ.get("OPENSSL", "openssl")


_passphrases = {}


def openssl(args, key):
    """Run OpenSSL on KEY, asking for its passphrase (if it has one) only the first time: it goes to
    OpenSSL through a pipe (-passin fd:N), never on a command line or in the environment."""
    if "ENCRYPTED" not in open(key).read(200):
        return subprocess.run([OPENSSL, *args], stdout=subprocess.PIPE)
    if key not in _passphrases: _passphrases[key] = getpass.getpass("Passphrase for %s: " % key)
    r, w = os.pipe()
    try:
        os.write(w, _passphrases[key].encode() + b"\n"); os.close(w)
        res = subprocess.run([OPENSSL, *args, "-passin", "fd:%d" % r], stdout=subprocess.PIPE, pass_fds=(r,))
    finally:
        os.close(r)
    if res.returncode: _passphrases.pop(key, None)                      # (a wrong one: ask again next time)
    return res


def public_key(key):
    """The raw 32-byte Ed25519 public key of a private key file (PEM)."""
    r = openssl(["pkey", "-in", key, "-pubout", "-outform", "DER"], key)
    if r.returncode or len(r.stdout) != 44: sys.exit("can't read the key %s (wrong passphrase? an Ed25519 key, OpenSSL 3.0 or newer?)" % key)
    return r.stdout[-32:]


def statement(tar, meta, pub):
    """The lines the signature covers (modinstall's format)."""
    data = open(tar, "rb").read()
    return ("licheepi-module 1\nid %s\nname %s\nversion %s\napi %d\nsize %d\nsha512 %s\nkey %s\n" % (
        meta["id"], meta.get("name", meta["id"]).replace("\n", " "), meta["version"], meta.get("api", 1),
        len(data), hashlib.sha512(data).hexdigest(), pub[:8].hex())).encode()


def sign(tar, meta, key):
    """Write TAR.sig: the statement, and its Ed25519 signature by KEY (OpenSSL asks for its passphrase)."""
    text = statement(tar, meta, public_key(key))
    with tempfile.TemporaryDirectory() as tmp:
        msg, sig = os.path.join(tmp, "statement"), os.path.join(tmp, "sig")
        open(msg, "wb").write(text)
        if openssl(["pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", msg, "-out", sig], key).returncode:
            sys.exit("signing failed (OpenSSL 3.0 or newer, an Ed25519 key?)")
        raw = open(sig, "rb").read()
    assert len(raw) == 64
    open(tar + ".sig", "wb").write(text + b"sig " + raw.hex().encode() + b"\n")
    return tar + ".sig"


def pack(name, key=None, themes=()):
    entries, meta = files(name, themes)
    assert meta.get("id") == name, "module.json's id (%s) must be its folder's name (%s)" % (meta.get("id"), name)
    assert all(c.isdigit() or c == "." for c in str(meta.get("version", ""))), "version: numbers and dots"
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
    if key: print("signed:", os.path.relpath(sign(out, meta, key), REPO))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    key = a[a.index("--key") + 1] if "--key" in a else None
    themes = a[a.index("--themes") + 1].split() if "--themes" in a else ()
    pack(a[0], key, themes)
