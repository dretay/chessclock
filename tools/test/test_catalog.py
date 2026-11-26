#!/usr/bin/env -S uv run -q python
"""The app catalog (apps/system/catalog.py, Get apps in the picker) on the desktop, without GitHub: a
catalog of the countdown runtime and the castle, signed with a throwaway key and served from a local
web server; the board's code loads and checks it with modinstall, sees the castle as "Install",
installs it (its runtime first), then sees it "Installed"; a catalog changed after signing is refused.
Needs a C compiler, zlib and OpenSSL 3. Run by tools/test/check.py, or by itself.
"""
import functools, http.server, json, os, shutil, subprocess, sys, tempfile, threading

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "apps")); sys.path.insert(0, os.path.join(REPO, "apps", "system"))
import pack, layout
SRC = os.path.join(REPO, "package", "modinstall", "src")
failures = []


def expect(what, ok, detail=""):
    print("%s  %-46s %s" % ("ok  " if ok else "FAIL", what, detail))
    if not ok: failures.append(what)


def main():
    tmp = tempfile.mkdtemp(prefix="catalog-test-")
    try:
        mi = os.path.join(tmp, "modinstall")
        r = subprocess.run(["cc", "-Os", "-o", mi, "modinstall.c", "monocypher/monocypher.c", "monocypher/monocypher-ed25519.c", "-lz"],
                           cwd=SRC, capture_output=True, text=True)
        if r.returncode: print("FAIL  compiling modinstall:", r.stderr[-300:]); return 1
        key = os.path.join(tmp, "k.pem")
        subprocess.run([pack.OPENSSL, "genpkey", "-algorithm", "ed25519", "-out", key], check=True, capture_output=True)
        open(os.path.join(tmp, "trusted.keys"), "w").write(pack.public_key(key).hex() + " test\n")
        wrapper = os.path.join(tmp, "mi.sh")                     # (the board's modinstall, with the test's keys)
        open(wrapper, "w").write('#!/bin/sh\nexec "%s" --keys "%s" "$@"\n' % (mi, os.path.join(tmp, "trusted.keys")))
        os.chmod(wrapper, 0o755)
        os.environ["MODINSTALL"] = wrapper
        import catalog

        www = os.path.join(tmp, "www"); os.makedirs(www)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=www))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % server.server_address[1]

        entries = []
        for n in ("system", "countdown", "castle"):
            tar = pack.pack(n, board=False)
            meta = layout.manifest(n)
            if n in ("system", "countdown"): meta["provides_api"] = int(open(os.path.join(REPO, "apps", n, "API")).read())
            dst = os.path.join(www, os.path.basename(tar)); shutil.copy(tar, dst); pack.sign(dst, meta, key)
            e = {"id": n, "name": meta["name"], "version": meta["version"], "api": meta.get("api", 1),
                 "url": base + os.path.basename(dst), "sig": base + os.path.basename(dst) + ".sig"}
            if meta.get("runtime"): e["runtime"] = meta["runtime"]
            if meta.get("kind"): e["kind"] = meta["kind"]
            entries.append(e)
        cpath = os.path.join(www, "catalog.json")
        json.dump({"apps": entries}, open(cpath, "w"), indent=1)
        pack.sign(cpath, {"id": "catalog", "name": "App catalog", "version": "2026.11.24", "api": 0}, key)

        root = os.path.join(tmp, "apps"); os.makedirs(os.path.join(root, "data"))
        work = os.path.join(root, "data", "packages")
        cat = catalog.load(base + "catalog.json", work)
        expect("loads the signed catalog", len(cat.get("apps", [])) == 3, "%d apps" % len(cat.get("apps", [])))
        castle = next(e for e in cat["apps"] if e["id"] == "castle")
        expect("the castle: Install", catalog.status(castle, root) == "Install", catalog.status(castle, root))
        seen = []
        out = catalog.install(castle, cat, root, work, progress=lambda f: seen.append(f), say=lambda s: seen.append(s))
        expect("installs it, the runtimes first", os.path.isdir(os.path.join(root, "system")) and os.path.isdir(os.path.join(root, "countdown")) and os.path.isdir(os.path.join(root, "castle")), out)
        expect("  with progress", any(isinstance(s, float) for s in seen) and "Installing Magic Kingdom" in seen)
        expect("  and cleans up the downloads", not [f for f in os.listdir(work) if f.endswith(".tar.gz")])
        expect("the castle: Installed", catalog.status(castle, root) == "Installed", catalog.status(castle, root))
        r = subprocess.run([wrapper, "--verify-installed", os.path.join(root, "castle")], capture_output=True, text=True)
        expect("  and it's signed (--verify-installed)", r.returncode == 0, r.stdout.strip())

        # ---- a base system update in the same catalog (publish.py --base beside apps): the board's slots are
        # a stand-in bootslot whose install runs the real modinstall --base onto a file for slot B
        images = os.path.join(tmp, "images"); os.makedirs(images)
        image = bytes((i * 31 + i // 512) & 0xff for i in range(2 << 20))
        open(os.path.join(images, "rootfs.ext4"), "wb").write(image)
        open(os.path.join(images, "base-version"), "w").write("2025.02.20.3\n")
        vfile = os.path.join(tmp, "base-version"); open(vfile, "w").write("2025.02.20.2\n")
        slot_b, state = os.path.join(tmp, "slot-b.img"), os.path.join(tmp, "slots")
        open(slot_b, "wb").write(b"\0" * (4 << 20)); open(state, "w").write("running: a\nworks: a\n")
        fake = os.path.join(tmp, "bootslot")
        open(fake, "w").write('#!/bin/sh\ncase "$1" in\n'
                              ' status) cat "%s" ;;\n'
                              ' install) "%s" --version-file "%s" --base --target "%s" "$2" || exit 1; echo "trying: b" >> "%s"; echo "slot b is tried at the next start" ;;\n'
                              ' clear-failed) grep -v failed "%s" > "%s.t"; mv "%s.t" "%s" ;;\nesac\n'
                              % (state, wrapper, vfile, slot_b, state, state, state, state, state))
        os.chmod(fake, 0o755)
        catalog.BOOTSLOT, catalog.BASE_VERSION = fake, vfile
        pkg, sig = pack.pack_base(images, key, out_dir=www)
        data = json.load(open(cpath))
        data["base"] = {"version": "2025.02.20.3", "board": pack.BOARD, "size": os.path.getsize(pkg),
                        "url": base + os.path.basename(pkg), "sig": base + os.path.basename(sig)}
        json.dump(data, open(cpath, "w"), indent=1)
        pack.sign(cpath, {"id": "catalog", "name": "App catalog", "version": "2026.11.25", "api": 0}, key)
        cat = catalog.load(base + "catalog.json", work)
        b = catalog.base_entry(cat)
        expect("base: the catalog has apps and a base update", b is not None and len(cat["apps"]) == 3, b and b["version"])
        expect("base: Update (newer than the running one)", catalog.base_status(b) == "Update", catalog.base_status(b))
        expect("base: none on a card without slots", catalog.base_status(b, {}) is None)
        expect("base: another board's is ignored", catalog.base_entry(dict(cat, base=dict(b, board="orangepi"))) is None)
        seen = []
        out = catalog.install_base(b, work, progress=lambda f: seen.append(f), say=lambda s: seen.append(s))
        expect("base: installs it into the other slot", open(slot_b, "rb").read(len(image)) == image, out)
        expect("  with progress", any(isinstance(s, float) for s in seen) and "Installing the base system" in seen)
        expect("  and cleans up the download", not [f for f in os.listdir(work) if f.endswith(".img.gz")])
        expect("base: then Restart", catalog.base_status(b) == "Restart", catalog.base_status(b))
        open(state, "w").write("running: b\nworks: b\n"); open(vfile, "w").write("2025.02.20.3\n")
        expect("base: Installed, once running it", catalog.base_status(b) == "Installed", catalog.base_status(b))
        expect("  and the apps still Installed beside it", catalog.status(castle, root) == "Installed")
        open(state, "w").write("running: a\nworks: a\n"); open(vfile, "w").write("2025.02.20.3\n")
        try: catalog.install_base(b, work); expect("base: refuses the same version again", False)
        except catalog.CatalogError as err: expect("base: refuses the same version again", "isn't newer" in str(err), str(err)[:60])

        data = json.load(open(cpath)); data["apps"][0]["url"] = "http://elsewhere.example/evil.tar.gz"
        json.dump(data, open(cpath, "w"), indent=1)
        try: catalog.load(base + "catalog.json", work); expect("refuses a changed catalog", False)
        except catalog.CatalogError as err: expect("refuses a changed catalog", True, str(err)[:60])
        server.shutdown()
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
