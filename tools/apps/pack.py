#!/usr/bin/env -S uv run -q python
"""Pack an app (apps/NAME) for publishing: a tarball of exactly what goes on the board, a manifest of
its files' SHA-256s, and (with a key) a signed statement for the board's modinstall.

    tools/apps/pack.py NAME [--key KEY.pem] [--local]
    -> build/packages/NAME-VERSION.tar.gz (+ .sig with --key)

What goes in is what tools/apps/layout.py lays out (the same as the SD card image and deploy.py put on
the board; --local: compiled for the Mac instead, for tests). The tarball is reproducible: files in
order, owned by root, timestamps 0. MANIFEST.json inside it: the app's id, name, version, and each
file's size and SHA-256.

Signing (--key): the Ed25519 key tools/apps/keygen.sh made, and OpenSSL 3.0 or newer (not macOS's
LibreSSL; OPENSSL picks one). The .sig is a short statement, signed: the app's id, name, version and
api, the runtime it needs (a countdown app: `runtime countdown`) or the api it provides (the runtime:
`provides-api 2`), and the tarball's size and SHA-512 (the format: package/modinstall/src/modinstall.c).
The board checks it against the public keys in its /etc/modules/trusted.keys, then the tarball against
it: `modinstall NAME-VERSION.tar.gz`.
"""
import fnmatch, getpass, gzip, hashlib, io, json, os, subprocess, sys, tarfile, tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import layout


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
    extra = ""
    if meta.get("runtime"): extra += "runtime %s\n" % meta["runtime"]
    if meta.get("provides_api") is not None: extra += "provides-api %d\n" % meta["provides_api"]
    return ("licheepi-module 1\nid %s\nname %s\nversion %s\napi %d\n%ssize %d\nsha512 %s\nkey %s\n" % (
        meta["id"], meta.get("name", meta["id"]).replace("\n", " "), meta["version"], meta.get("api", 1), extra,
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


def pack(name, key=None, board=True):
    meta = layout.manifest(name)
    assert meta.get("id") == name, "app.json's id (%s) must be its folder's name (%s)" % (meta.get("id"), name)
    assert all(c.isdigit() or c == "." for c in str(meta.get("version", ""))), "version: numbers and dots"
    stage = layout.layout(name, os.path.join(REPO, "build", "apps", name), board)
    entries = sorted((os.path.relpath(os.path.join(d, f), stage), os.path.join(d, f))
                     for d, _, fs in os.walk(stage) for f in fs if not f.endswith(".pyc") and "__pycache__" not in d)
    if os.path.isfile(os.path.join(stage, "API")):                      # (a runtime: the app api it provides)
        meta = dict(meta, provides_api=int(open(os.path.join(stage, "API")).read().strip()))
    manifest = {k: meta.get(k) for k in ("id", "name", "version", "api", "runtime")}
    manifest["files"] = {rel: {"size": os.path.getsize(p), "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
                         for rel, p in entries}
    out_dir = os.path.join(REPO, "build", "packages"); os.makedirs(out_dir, exist_ok=True)
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
    pack(a[0], key, "--local" not in a)
