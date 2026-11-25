#!/usr/bin/env python3
"""Check the countdown apps (the cruise, the castle) and their runtime on a desktop, with the device's
own drawing code:

    tools/test/check.py                 the checks below, and renders into build/test/now/
    tools/test/check.py --save NAME     ... and keep those renders as the baseline NAME (build/test/NAME/)
    tools/test/check.py --compare NAME  ... and compare them with the baseline NAME, pixel for pixel

1. every app's app.json parses; a countdown app's names what's there (its screens, its default scene
   with everything the drawing library loads, an executable run, and service if it has one);
2. every Python file of the apps compiles; and modinstall (tools/test/test_modinstall.py) installs a
   signed app and refuses tampered or unsafe ones; awkward photos (tools/test/test_photos.py: no sky, tiny,
   portrait, dark, flat...) each become a scene that runs, in seconds;
3. renders, per countdown app: the countdown at noon and at 10 PM, and its screens (with their example data),
   on the preview clock (VACATION_SIM_CLOCK: the same frames every run), as PNGs, with the frames'
   SHA-256 in hashes.json. --compare reports which differ (and writes a diff image of each).

Run it before and after a change that shouldn't change what's on screen (--save, then --compare).
A baseline guards the shared code (the runtime, the drawing library), not the apps' own looks: it keeps
a fingerprint of each app's own files (content.json), and --compare takes an app whose files have changed
since (a scene kept, its screens, its settings: your edits), or that's new, as its own new baseline,
saying so; only an app whose files are as they were has to match.
Needs a C compiler (cc), zlib and Pillow. Exits non-zero if a check fails or a render differs.
"""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS = os.path.join(REPO, "apps")
APP = os.path.join(APPS, "countdown")                     # the runtime
SYSTEM = os.path.join(APPS, "system")                     # (its drawing library, Settings, the picker)
OUT = os.path.join(REPO, "build", "test")
W, H = 800, 480
SCENE_FILES = ("day.rgb.gz", "dusk.rgb.gz", "night.rgb.gz", "lights.bin.gz", "cards.bin.gz", "theme.json")
failures = []


def fail(msg): failures.append(msg); print("FAIL", msg)


def check_modules():
    mods = []
    for p in sorted(glob.glob(os.path.join(APPS, "*", "app.json"))):
        d = os.path.dirname(p); name = os.path.basename(d)
        try: m = json.load(open(p))
        except ValueError as e: fail("%s: app.json: %s" % (name, e)); continue
        for k in ("id", "name", "version"):
            if k not in m: fail("%s: app.json has no %s" % (name, k))
        if m.get("id") != name: fail("%s: id is %r, its folder %r" % (name, m.get("id"), name))
        if m.get("kind") != "runtime" and not os.access(os.path.join(d, "run"), os.X_OK): fail("%s: no executable run" % name)
        if m.get("runtime") != "countdown": continue
        mods.append(name)
        for k in ("api", "scene"):
            if k not in m: fail("%s: app.json has no %s" % (name, k))
        sc = m.get("scene", {}); scene = os.path.join(d, sc.get("dir", "scenes"), sc.get("default", ""))
        for f in SCENE_FILES:
            if not os.path.exists(os.path.join(scene, f)): fail("%s: scene %s has no %s" % (name, sc.get("default"), f))
        if not (os.path.exists(os.path.join(scene, "mask.raw.gz")) or os.path.exists(os.path.join(scene, "ship.raw.gz"))):
            fail("%s: scene %s has no mask.raw.gz" % (name, sc.get("default")))
        sys.path.insert(0, os.path.join(APPS, "countdown")); import screens as screen_types
        for s in m.get("screens", []):
            if s.get("type") and s["type"] not in screen_types.TYPES: fail("%s: screen type %s: there's no such type" % (name, s["type"])); continue
            s = screen_types.resolve(s)                                                       # (a type: the runtime's file)
            where = os.path.join(APPS, "countdown") if s.get("from") == "runtime" else d       # (a screen the runtime has: the parks' board)
            if not os.path.exists(os.path.join(where, s.get("file", ""))): fail("%s: screen %s: no %s" % (name, s.get("id") or s.get("type"), s.get("file")))
            if s.get("fetch") and not os.path.exists(os.path.join(APPS, "countdown", s["fetch"])): fail("%s: screen %s: no fetcher %s" % (name, s.get("type"), s["fetch"]))
        svc = os.path.join(d, "service")
        if os.path.exists(svc) and not os.access(svc, os.X_OK): fail("%s: service isn't executable" % name)
        for st in m.get("settings", []):
            if st.get("type") not in ("one", "many"): fail("%s: setting %s: type %r" % (name, st.get("key"), st.get("type")))
            if "options" not in st and "options_from" not in st: fail("%s: setting %s has no options" % (name, st.get("key")))
    if not mods: fail("no countdown apps")
    return mods


def check_python():
    for p in glob.glob(os.path.join(APPS, "*", "*.py")) + glob.glob(os.path.join(APPS, "*", "tools", "*.py")):
        try: compile(open(p).read(), p, "exec")
        except SyntaxError as e: fail("compile %s: %s" % (os.path.relpath(p, REPO), e))


def render(mods, out):
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="vacation-check-")
    lib = os.path.join(tmp, "libvacfx.so")
    r = subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", lib, os.path.join(SYSTEM, "fx", "vacfx.c"), "-lz"], capture_output=True, text=True)
    if r.returncode: fail("compiling the drawing library: %s" % r.stderr[-400:]); return {}
    F = W * H * 4; hashes = {}
    for mod in mods:
        data = os.path.join(tmp, mod); os.makedirs(data)
        conf = os.path.join(data, "countdown.conf")
        own = os.path.join(APPS, mod, "defaults.conf")
        with open(conf, "w") as f:
            f.write(open(os.path.join(APP, "countdown.conf")).read() + "\n" + (open(own).read() if os.path.exists(own) else "") + "\nTHEME=\n")
        env = dict(os.environ, APP_DATA=data, VACATION_APP=os.path.join(APPS, mod), VACATION_LIB=lib, VACATION_CONF=conf,
                   VACATION_NOW="2026-11-22T12:00",
                   VACATION_SIM_CLOCK="0", VACATION_FB=os.path.join(tmp, "fb.raw"))
        shots = [("noon", {"VACATION_HOUR": "12", "VACATION_SIM_END": "2", "VACATION_MAP_AFTER": "99"}, -1),
                 ("night", {"VACATION_HOUR": "22", "VACATION_SIM_END": "2", "VACATION_MAP_AFTER": "99"}, -1),
                 ("screen", {"VACATION_HOUR": "12", "VACATION_SIM_END": "4", "VACATION_MAP_AFTER": "1"}, 0.5)]
        for shot, extra, at in shots:
            rec = os.path.join(tmp, "rec.raw")
            if os.path.exists(rec): os.remove(rec)
            r = subprocess.run([sys.executable, os.path.join(APP, "vacation.py")], env=dict(env, VACATION_RECORD=rec, **extra),
                               capture_output=True, text=True, cwd=os.path.join(APPS, mod))
            if r.returncode or not os.path.exists(rec): fail("%s %s: the app failed: %s" % (mod, shot, r.stderr[-400:])); continue
            raw = open(rec, "rb").read(); n = len(raw) // F
            frame = raw[(n - 1) * F:n * F] if at < 0 else raw[int(n * at) * F:(int(n * at) + 1) * F]
            key = "%s-%s" % (mod, shot)
            hashes[key] = hashlib.sha256(raw).hexdigest()                 # (every frame: the whole run must match)
            Image.frombytes("RGB", (W, H), frame, "raw", "BGRX").save(os.path.join(out, key + ".png"))
            print("rendered", key, "(%d frames)" % n)
    json.dump(hashes, open(os.path.join(out, "hashes.json"), "w"), indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    return hashes


def check_picker(out):
    """The app picker (apps/system/picker.py) over the apps here: drawn, and a tap on the cruise picks it."""
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="picker-check-")
    lib = os.path.join(tmp, "libvacfx.so")
    subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", lib, os.path.join(SYSTEM, "fx", "vacfx.c"), "-lz"], check=True)
    names = [json.load(open(p))["name"] for p in glob.glob(os.path.join(APPS, "*", "app.json"))
             if os.access(os.path.join(os.path.dirname(p), "run"), os.X_OK)]
    i = sorted(names, key=str.lower).index("Disney cruise")
    x = 20 + (i % 3) * 260 + 120
    open(os.path.join(tmp, "taps"), "w").write("1.0 %d 240 0.1\n" % x)
    r = subprocess.run([sys.executable, os.path.join(SYSTEM, "picker.py")], capture_output=True, text=True,
                       env=dict(os.environ, PICKER_APPS=APPS, PICKER_CURRENT="castle", PICKER_TIMEOUT="3", VACATION_LIB=lib,
                                VACATION_FB=os.path.join(tmp, "fb.raw"), VACATION_TOUCH_SCRIPT=os.path.join(tmp, "taps")))
    if r.returncode or r.stdout.strip() != "cruise": fail("picker: tapped the cruise, got %r %s" % (r.stdout.strip(), r.stderr[-300:]))
    else:
        Image.frombytes("RGB", (W, H), open(os.path.join(tmp, "fb.raw"), "rb").read()[:W * H * 4], "raw", "BGRX").save(os.path.join(out, "picker.png"))
        print("picker: %d apps, a tap on the cruise picks it" % len(names))
    shutil.rmtree(tmp, ignore_errors=True)


def fingerprint(mod):
    """An app's own files (its scene, app.json, settings, screens' examples: what the app's author changes),
    as one SHA-256; not the shared code it runs on."""
    h = hashlib.sha256(); d = os.path.join(APPS, mod)
    for root, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if f == "preview.png" or f.endswith(".pyc"): continue
            p = os.path.join(root, f); h.update(os.path.relpath(p, d).encode() + b"\0")
            with open(p, "rb") as fh: h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def compare(now, name, mods):
    from PIL import Image, ImageChops
    base = os.path.join(OUT, name)
    try: old = json.load(open(os.path.join(base, "hashes.json")))
    except OSError: fail("no baseline %s (make one with --save %s)" % (name, name)); return
    try: content = json.load(open(os.path.join(base, "content.json")))
    except (OSError, ValueError): content = None                        # (a baseline from before fingerprints: all of it as it is)
    SHOTS = ("noon", "night", "screen")
    def keys(m): return ["%s-%s" % (m, s) for s in SHOTS]
    if content is None: content = {m: fingerprint(m) for m in mods if any(k in old for k in keys(m))}
    # an app whose own files changed since the baseline (or a new one): what it looks like now is its baseline
    renewed = []
    for m in mods:
        fp = fingerprint(m)
        if content.get(m) == fp: continue
        for k in [k for k in keys(m) if k in now]:
            old[k] = now[k]; shutil.copy(os.path.join(OUT, "now", k + ".png"), os.path.join(base, k + ".png"))
        print("%s: %s: its renders are its baseline now" % (m, "new" if m not in content else "its own files changed (your edits)"))
        content[m] = fp; renewed.append(m)
    for m in [m for m in content if m not in mods]:                      # (an app that's gone)
        for k in keys(m): old.pop(k, None)
        content.pop(m); renewed.append(m); print("%s: gone: dropped from the baseline" % m)
    if renewed:
        json.dump(old, open(os.path.join(base, "hashes.json"), "w"), indent=1)
    json.dump(content, open(os.path.join(base, "content.json"), "w"), indent=1)
    for k in sorted(set(old) | set(now)):
        if k not in now or k not in old: fail("%s: only in %s" % (k, "the baseline" if k in old else "this run")); continue
        if old[k] == now[k]: print("same", k); continue
        fail("%s differs from the baseline %s" % (k, name))
        a, b = os.path.join(base, k + ".png"), os.path.join(OUT, "now", k + ".png")
        if os.path.exists(a) and os.path.exists(b):
            d = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")).point(lambda v: min(255, v * 8))
            d.save(os.path.join(OUT, "now", k + ".diff.png")); print("    diff:", os.path.relpath(os.path.join(OUT, "now", k + ".diff.png"), REPO))


def main():
    args = sys.argv[1:]
    mods = check_modules(); check_python()
    r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "test", "test_modinstall.py")], capture_output=True, text=True)
    if r.returncode: fail("modinstall:\n" + "\n".join(l for l in (r.stdout + r.stderr).splitlines() if not l.startswith("ok")))
    else: print("modinstall: installs signed apps, refuses the rest (%d checks)" % r.stdout.count("\nok"))
    r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "test", "test_catalog.py")], capture_output=True, text=True)
    if r.returncode: fail("catalog:\n" + "\n".join(l for l in (r.stdout + r.stderr).splitlines() if not l.startswith("ok")))
    else: print("catalog: a signed catalog loads and installs (runtime first), a changed one is refused")
    r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "test", "test_photos.py")], capture_output=True, text=True)
    if r.returncode: fail("photos:\n" + "\n".join(l for l in (r.stdout + r.stderr).splitlines() if not l.startswith("ok")))
    else: print("photos: %d awkward ones (no sky, tiny, dark, flat...) each a scene that runs, in seconds" % r.stdout.count("ok "))
    now = render(mods, os.path.join(OUT, "now"))
    check_picker(os.path.join(OUT, "now"))
    if "--save" in args:
        name = args[args.index("--save") + 1]; dst = os.path.join(OUT, name)
        shutil.rmtree(dst, ignore_errors=True); shutil.copytree(os.path.join(OUT, "now"), dst)
        json.dump({m: fingerprint(m) for m in mods}, open(os.path.join(dst, "content.json"), "w"), indent=1)
        print("baseline saved:", os.path.relpath(dst, REPO))
    if "--compare" in args: compare(now, args[args.index("--compare") + 1], mods)
    print("%d problem(s)" % len(failures) if failures else "all good")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
