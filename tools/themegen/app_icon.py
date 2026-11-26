#!/usr/bin/env python3
"""Each app's picture for the app picker (apps/system/picker.py): apps/<id>/icon.rgb.gz, 240x144
raw RGB, gzipped without a timestamp (the same picture makes the same file).

    python3 tools/themegen/app_icon.py [NAME ...]          (default: every app that has a picture)

From a countdown app's default scene (its day plate, 800x480: the same shape, scaled down), or else its
boot splash (800x480, the screen's own 32-bit pixels: BGRX). Needs Pillow.
"""
import gzip, json, os, sys
from PIL import Image

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS = os.path.join(REPO, "apps")
W, H = 240, 144


def source(name):
    d = os.path.join(APPS, name)
    meta = json.load(open(os.path.join(d, "app.json")))
    sc = meta.get("scene")
    if sc:
        plate = os.path.join(d, sc.get("dir", "scenes"), sc["default"], "day.rgb.gz")
        return Image.frombytes("RGB", (800, 480), gzip.open(plate).read())
    splash = os.path.join(d, "splash", "splash-800x480x32-0.raw.gz")
    if os.path.isfile(splash):
        return Image.frombytes("RGB", (800, 480), gzip.open(splash).read(), "raw", "BGRX")
    return None


def icon(name):
    """Write the app's icon.rgb.gz from its picture (None when it has none)."""
    img = source(name)
    if img is None: return None
    out = os.path.join(APPS, name, "icon.rgb.gz")
    with gzip.GzipFile(out, "wb", 9, mtime=0) as f: f.write(img.resize((W, H), Image.LANCZOS).tobytes())
    print("icon:", os.path.relpath(out, REPO))
    return out


def main():
    names = sys.argv[1:] or sorted(n for n in os.listdir(APPS) if os.path.isfile(os.path.join(APPS, n, "app.json")))
    for name in names: icon(name)


if __name__ == "__main__":
    main()
