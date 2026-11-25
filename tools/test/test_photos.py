#!/usr/bin/env python3
"""Awkward photos through the Scene Builder's steps (tools/themegen/photo_scene.py): each must come out a
scene that runs, in seconds, never hang. Made up here (no photos in the repo), into a temporary folder:

    no-sky     indoors, warm, no sky at all (the train in its station)
    tiny       160 x 120 (enlarged a lot)
    portrait   taller than wide (cut to the screen's shape)
    dark       nearly black
    all-water  water everywhere, no sky
    all-sky    sky everywhere, nothing in front
    flat       one flat grey, no texture at all
    no-orb     a landscape, with "find the lights on a sphere" asked for and no sphere there

For each: the photo made into a scene (by colour: the AI model is left out, PHOTO_SCENE_NO_AI, so this is
quick and the same every time), windows and water found automatically, then the countdown run at night
with fireworks for a few seconds on the device's drawing code. Each photo has LIMIT seconds; a step that
fails or takes longer is a failure. Prints one line each ("ok NAME (1.2 s)"); exits non-zero on any failure.
"""
import os, random, shutil, subprocess, sys, tempfile, time

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LIMIT = 90


def photos(d):
    from PIL import Image, ImageDraw, ImageFilter
    rnd = random.Random(5)
    def noisy(w, h, top, bottom, amount=24):
        im = Image.new("RGB", (w, h)); dr = ImageDraw.Draw(im)
        for y in range(h):
            t = y / max(1, h - 1); dr.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
        n = Image.effect_noise((w, h), amount).convert("RGB")
        return Image.blend(im, n, 0.12).filter(ImageFilter.GaussianBlur(0.6))
    def landscape(w, h):
        im = noisy(w, h, (90, 150, 215), (200, 225, 240)); dr = ImageDraw.Draw(im)
        dr.rectangle([0, int(h * 0.62), w, h], fill=(70, 96, 60))
        for _ in range(12):
            x = rnd.uniform(0, w); dr.ellipse([x - 40, h * 0.5, x + 40, h * 0.68], fill=(40, 70, 40))
        dr.rectangle([w * 0.4, h * 0.3, w * 0.55, h * 0.62], fill=(180, 170, 150))   # (a building, with windows)
        for k in range(6): dr.rectangle([w * 0.42 + k * 12, h * 0.4, w * 0.42 + k * 12 + 6, h * 0.45], fill=(40, 40, 50))
        return im
    out = {
        "no-sky": (noisy(1200, 900, (120, 70, 40), (60, 40, 30)), None),
        "tiny": (landscape(160, 120), None),
        "portrait": (landscape(600, 1100), None),
        "dark": (noisy(1000, 600, (8, 8, 12), (2, 2, 4), 8), None),
        "all-water": (noisy(1000, 600, (40, 90, 130), (20, 60, 100)), None),
        "all-sky": (noisy(1000, 600, (80, 140, 220), (190, 220, 245), 6), None),
        "flat": (Image.new("RGB", (900, 540), (128, 128, 128)), None),
        "no-orb": (landscape(1000, 600), "auto"),
    }
    for name, (im, orb) in out.items():
        p = os.path.join(d, name + ".jpg"); im.save(p, quality=88); out[name] = (p, orb)
    return out


STEPS = r'''
import sys; sys.path.insert(0, sys.argv[1])
import photo_scene
photo, work, scene, orb = sys.argv[2:6]
photo_scene.make(photo, work, scene, None, orb or None, False)
photo_scene.find_windows_into(work, scene)
photo_scene.find_water_into(work, scene)
'''


def main():
    tmp = tempfile.mkdtemp(prefix="photo-check-")
    lib = os.path.join(tmp, "libvacfx.so")
    r = subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", lib, os.path.join(REPO, "apps", "system", "fx", "vacfx.c"), "-lz"],
                       capture_output=True, text=True)
    if r.returncode: print("FAIL compiling the drawing library:", r.stderr[-300:]); sys.exit(1)
    bad = 0
    env = dict(os.environ, PHOTO_SCENE_NO_AI="1", THEME_WORK=os.path.join(tmp, "unused"))
    for name, (photo, orb) in photos(tmp).items():
        work, scene, data = (os.path.join(tmp, name, k) for k in ("work", "scene", "data"))
        os.makedirs(data); t0 = time.time()
        try:
            r = subprocess.run([sys.executable, "-c", STEPS, os.path.join(REPO, "tools", "themegen"), photo, work, scene, orb or ""],
                               capture_output=True, text=True, env=env, timeout=LIMIT)
            if r.returncode: raise RuntimeError("making the scene: " + (r.stderr.strip().splitlines() or ["?"])[-1])
            left = max(5, LIMIT - (time.time() - t0))
            r = subprocess.run([sys.executable, os.path.join(REPO, "apps", "countdown", "vacation.py")], capture_output=True, text=True,
                               timeout=left, cwd=os.path.join(REPO, "apps", "castle"),
                               env=dict(env, VACATION_APP=os.path.join(REPO, "apps", "castle"), VACATION_SCENE_DIR=scene, APP_DATA=data,
                                        VACATION_LIB=lib, VACATION_FB=os.path.join(tmp, "fb.raw"), VACATION_HOUR="22",
                                        VACATION_FIREWORKS="1", VACATION_SIM_CLOCK="0", VACATION_SIM_END="4", VACATION_MAP_AFTER="99"))
            if r.returncode: raise RuntimeError("running it: " + (r.stderr.strip().splitlines() or ["?"])[-1])
            print("ok %s (%.1f s)" % (name, time.time() - t0))
        except subprocess.TimeoutExpired:
            bad += 1; print("FAIL %s: still going after %d s (stuck?)" % (name, LIMIT))
        except RuntimeError as e:
            bad += 1; print("FAIL %s: %s" % (name, e))
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
