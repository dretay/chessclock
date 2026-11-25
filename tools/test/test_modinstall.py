#!/usr/bin/env -S uv run -q python
"""modinstall (package/modinstall), on the desktop: it installs apps signed by a trusted key (the
countdown runtime, then the castle on it), and refuses everything else - a changed tarball or
statement, an untrusted key, an older version, an app without its runtime or with too old a one, a
runtime too old for an installed app, the names /apps's other things have, replacing what isn't an
app, and tarballs reaching outside the app (.., absolute paths, links). Uses a throwaway key; needs a
C compiler, zlib, and OpenSSL 3 (OPENSSL picks one). Run by tools/test/check.py, or by itself.
"""
import gzip, io, os, shutil, subprocess, sys, tarfile, tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "apps")); import pack, layout
SRC = os.path.join(REPO, "package", "modinstall", "src")
failures = []


def run(tmp, *args):
    r = subprocess.run([os.path.join(tmp, "modinstall"), "--keys", os.path.join(tmp, "trusted.keys"),
                        "--dir", os.path.join(tmp, "apps"), *args], capture_output=True, text=True)
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
        mods = os.path.join(tmp, "apps"); os.makedirs(os.path.join(mods, "data"))

        def packed(name, sign_meta=None):
            """apps/NAME packed (for the desktop) and signed with the test key, as tmp/NAME.tar.gz"""
            tar = pack.pack(name, board=False)
            dst = os.path.join(tmp, name + ".tar.gz"); shutil.copy(tar, dst)
            meta = layout.manifest(name)
            if os.path.isfile(os.path.join(REPO, "build", "apps", name, "API")):
                meta["provides_api"] = int(open(os.path.join(REPO, "build", "apps", name, "API")).read())
            pack.sign(dst, sign_meta or meta, key)
            return dst, meta

        good, meta = packed("castle")
        system, smeta = packed("system")
        runtime, rmeta = packed("countdown")
        expect("--check, a good app", True, run(tmp, "--check", good), "ok: castle")
        expect("an app before its runtime", False, run(tmp, good), "isn't installed: install it first")
        expect("the countdown runtime before the system", False, run(tmp, runtime), "isn't installed: install it first")
        expect("install the system package", True, run(tmp, system), "installed system")
        expect("install the runtime", True, run(tmp, runtime), "installed countdown")
        expect("install the app", True, run(tmp, good), "installed castle")
        want = sorted(rel for rel, _ in layout.files("castle")) + [".signature", "MANIFEST.json"]
        got = sorted(os.path.relpath(os.path.join(d, f), os.path.join(mods, "castle"))
                     for d, _, fs in os.walk(os.path.join(mods, "castle")) for f in fs)
        expect("  every file, and nothing else", sorted(want) == got, (0, "%d files" % len(got)))
        def verify(d):
            r = subprocess.run([os.path.join(tmp, "modinstall"), "--keys", os.path.join(tmp, "trusted.keys"),
                                "--verify-installed", os.path.join(mods, d)], capture_output=True, text=True)
            return r.returncode, (r.stdout + r.stderr).strip()
        expect("--verify-installed, a signed app", True, verify("castle"), "signed: castle")
        sig = os.path.join(mods, "castle", ".signature"); keep = open(sig).read()
        open(sig, "w").write(keep.replace("version " + meta["version"], "version 9.9.9"))
        expect("--verify-installed, an edited .signature", False, verify("castle"), "signature doesn't match")
        open(sig, "w").write(keep)
        rsig = os.path.join(mods, "countdown", ".signature"); rkeep = open(rsig).read(); os.remove(rsig)
        expect("--verify-installed, its runtime unsigned", False, verify("castle"), "isn't signed")
        open(rsig, "w").write(rkeep)
        ssig = os.path.join(mods, "system", ".signature"); skeep = open(ssig).read(); os.remove(ssig)
        expect("--verify-installed, its runtime's runtime unsigned", False, verify("castle"), "system isn't signed")
        open(ssig, "w").write(skeep)
        os.makedirs(os.path.join(mods, "dev")); open(os.path.join(mods, "dev", "app.json"), "w").write("{}")
        expect("--verify-installed, an unsigned app", False, verify("dev"), "isn't signed")
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
        expect("  back to the newer one", True, run(tmp, good), "installed castle")
        shutil.copy(good, bad); pack.sign(bad, dict(meta, api=meta["api"] + 1), key)
        expect("an api newer than the runtime's", False, run(tmp, bad), "needs a newer countdown runtime")
        shutil.copy(runtime, bad); pack.sign(bad, dict(rmeta, version="9.0", provides_api=1), key)
        expect("a runtime too old for an installed app", False, run(tmp, bad), "needs %d" % meta["api"])
        shutil.copy(good, bad); pack.sign(bad, dict(meta, id="data"), key)
        expect("an app called data (the data folder)", False, run(tmp, bad), "isn't a name an app can have")
        os.makedirs(os.path.join(mods, "notes")); open(os.path.join(mods, "notes", "x"), "w").write("mine")
        evil_tar(bad, [("notes/app.json", tarfile.REGTYPE, b'{"id": "notes"}')]); pack.sign(bad, dict(meta, id="notes", runtime=None), key)
        expect("replacing a folder that isn't an app", False, run(tmp, bad), "isn't an app")
        open(bad + ".sig", "w").write("not a statement\n")
        expect("not a statement", False, run(tmp, bad), "not a module statement")

        mj = b'{"id": "castle"}'
        for what, entries in [
                ("a .. path", [("castle/app.json", tarfile.REGTYPE, mj), ("castle/../escaped", tarfile.REGTYPE, b"x")]),
                ("an absolute path", [("/tmp/escaped", tarfile.REGTYPE, b"x")]),
                ("another module's folder", [("cruise/app.json", tarfile.REGTYPE, mj)]),
                ("a symlink", [("castle/app.json", tarfile.REGTYPE, mj), ("castle/link", tarfile.SYMTYPE, "/etc")]),
                ("a hard link", [("castle/app.json", tarfile.REGTYPE, mj), ("castle/hl", tarfile.LNKTYPE, b"")]),
                ("the same file twice", [("castle/app.json", tarfile.REGTYPE, mj), ("castle/app.json", tarfile.REGTYPE, mj)]),
                ("no app.json", [("castle/board.py", tarfile.REGTYPE, b"x")])]:
            evil_tar(bad, entries); pack.sign(bad, dict(meta, version="5.0"), key)
            before = sorted(os.listdir(mods))
            expect("refuses " + what, False, run(tmp, bad))
            expect("  and leaves the apps as they were", sorted(os.listdir(mods)) == before
                   and not os.path.exists(os.path.join(tmp, "app", "escaped")), (0, ""))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
