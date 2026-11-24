#!/usr/bin/env python3
"""modinstall (package/modinstall), on the desktop: it installs a module signed by a trusted key, and
refuses everything else - a changed tarball or statement, an untrusted key, an older version, a newer
api, and tarballs reaching outside the module (.., absolute paths, links). Uses a throwaway key; needs
a C compiler, zlib, and OpenSSL 3 (OPENSSL picks one). Run by tools/test/check.py, or by itself.
"""
import gzip, io, json, os, shutil, subprocess, sys, tarfile, tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "modules")); import pack
SRC = os.path.join(REPO, "package", "modinstall", "src")
failures = []


def run(tmp, *args):
    r = subprocess.run([os.path.join(tmp, "modinstall"), "--keys", os.path.join(tmp, "trusted.keys"),
                        "--dir", os.path.join(tmp, "app", "modules"), *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def expect(what, ok, result, contains=""):
    code, out = result
    good = (code == 0) == ok and contains in out
    print("%s  %-44s %s" % ("ok  " if good else "FAIL", what, out.splitlines()[-1] if out else ""))
    if not good: failures.append(what)


def evil_tar(path, entries):
    """A tarball with these (name, type, data) entries, gzipped."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for name, kind, data in entries:
            ti = tarfile.TarInfo(name); ti.type = kind
            if kind == tarfile.SYMTYPE: ti.linkname = data
            else: ti.size = len(data)
            t.addfile(ti, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    with gzip.GzipFile(path, "wb", mtime=0) as f: f.write(raw.getvalue())


def main():
    tmp = tempfile.mkdtemp(prefix="modinstall-test-")
    try:
        r = subprocess.run(["cc", "-Os", "-Wall", "-o", os.path.join(tmp, "modinstall"), "modinstall.c",
                            "monocypher/monocypher.c", "monocypher/monocypher-ed25519.c", "-lz"], cwd=SRC,
                           capture_output=True, text=True)
        if r.returncode: print("FAIL  compiling modinstall:", r.stderr[-400:]); return 1
        key, other = os.path.join(tmp, "k.pem"), os.path.join(tmp, "other.pem")
        for k in (key, other):
            subprocess.run([pack.OPENSSL, "genpkey", "-algorithm", "ed25519", "-out", k], check=True, capture_output=True)
        open(os.path.join(tmp, "trusted.keys"), "w").write("# test\n%s test key\n" % pack.public_key(key).hex())
        os.makedirs(os.path.join(tmp, "app", "modules"))
        open(os.path.join(tmp, "app", "modules.py"), "w").write("x = 1\nAPI = 1\n")
        mods = os.path.join(tmp, "app", "modules")

        tar = pack.pack("castle")
        meta = json.load(open(os.path.join(pack.MODULES, "castle", "module.json")))
        good = os.path.join(tmp, "castle.tar.gz"); shutil.copy(tar, good)
        pack.sign(good, meta, key)

        expect("--check, a good module", True, run(tmp, "--check", good), "ok: castle")
        expect("install it", True, run(tmp, good), "installed castle")
        want = sorted(rel for rel, _ in pack.files("castle")[0]) + [".signature", "MANIFEST.json"]
        got = sorted(os.path.relpath(os.path.join(d, f), os.path.join(mods, "castle"))
                     for d, _, fs in os.walk(os.path.join(mods, "castle")) for f in fs)
        expect("  every file, and nothing else", sorted(want) == got, (0, "%d files" % len(got)))
        expect("install it again (same version)", True, run(tmp, good), "was " + meta["version"])
        expect("  the old one kept", os.path.isdir(os.path.join(mods, ".old-castle")), (0, ""))

        bad = os.path.join(tmp, "changed.tar.gz"); b = bytearray(open(good, "rb").read()); b[len(b) // 2] ^= 1
        open(bad, "wb").write(b); shutil.copy(good + ".sig", bad + ".sig")
        expect("a changed tarball", False, run(tmp, bad), "doesn't match its statement")
        s = open(good + ".sig").read()
        shutil.copy(good, bad); open(bad + ".sig", "w").write(s.replace("version %s" % meta["version"], "version 9.9.9"))
        expect("a changed statement", False, run(tmp, bad), "signature doesn't match")
        shutil.copy(good, bad); pack.sign(bad, meta, other)
        expect("signed by an untrusted key", False, run(tmp, bad), "isn't trusted")
        shutil.copy(good, bad); pack.sign(bad, dict(meta, version="0.0.1"), key)
        expect("an older version", False, run(tmp, bad), "older than the installed")
        expect("an older version, --force", True, run(tmp, "--force", bad), "installed castle 0.0.1")
        shutil.copy(good, bad); pack.sign(bad, dict(meta, api=2), key)
        expect("a newer api than the host's", False, run(tmp, bad), "needs a newer app")
        open(bad + ".sig", "w").write("not a statement\n")
        expect("not a statement", False, run(tmp, bad), "not a module statement")

        mj = b'{"id": "castle"}'
        for what, entries in [
                ("a .. path", [("castle/module.json", tarfile.REGTYPE, mj), ("castle/../escaped", tarfile.REGTYPE, b"x")]),
                ("an absolute path", [("/tmp/escaped", tarfile.REGTYPE, b"x")]),
                ("another module's folder", [("cruise/module.json", tarfile.REGTYPE, mj)]),
                ("a symlink", [("castle/module.json", tarfile.REGTYPE, mj), ("castle/link", tarfile.SYMTYPE, "/etc")]),
                ("a hard link", [("castle/module.json", tarfile.REGTYPE, mj), ("castle/hl", tarfile.LNKTYPE, b"")]),
                ("the same file twice", [("castle/module.json", tarfile.REGTYPE, mj), ("castle/module.json", tarfile.REGTYPE, mj)]),
                ("no module.json", [("castle/board.py", tarfile.REGTYPE, b"x")])]:
            evil_tar(bad, entries); pack.sign(bad, dict(meta, version="5.0"), key)
            before = sorted(os.listdir(mods))
            expect("refuses " + what, False, run(tmp, bad))
            expect("  and leaves the modules as they were", sorted(os.listdir(mods)) == before
                   and not os.path.exists(os.path.join(tmp, "app", "escaped")), (0, ""))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
