#!/usr/bin/env python3
"""A countdown app's boot splash: apps/<id>/splash/splash-800x480x32-0.raw.gz, what its splash.sh
copies straight to the screen the moment the board's first startup script runs (/etc/init.d/S00app),
so the screen isn't black while the countdown starts. The app's scene behind Settings (its
settings_bg.rgb.gz: blurred and dimmed), its name, and "Starting", in the screen's own pixels
(BGRX), gzipped without a timestamp; and splash/dots, where the three dots after "Starting" go
(x y of the first one's centre), which the countdown runtime's splashanim animates.

    python3 tools/themegen/app_splash.py [NAME ...]          (default: every countdown app)

Needs Pillow and the Cormorant Garamond fonts in assets/fonts (see the cruise scene's SOURCES.md).
"""
import gzip, json, os, sys
from PIL import Image, ImageDraw, ImageFont

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS = os.path.join(REPO, "apps")
FONTS = os.path.join(REPO, "assets", "fonts")
W, H = 800, 480
IVORY, GOLD, DIM = (244, 238, 222), (226, 190, 120), (170, 176, 190)


def font(size, weight=600):
    f = ImageFont.truetype(os.path.join(FONTS, "CormorantGaramond[wght].ttf"), size)
    try: f.set_variation_by_axes([weight])
    except (OSError, AttributeError): pass
    return f


def splash(name):
    d = os.path.join(APPS, name)
    meta = json.load(open(os.path.join(d, "app.json")))
    sc = meta["scene"]
    scene = os.path.join(d, sc.get("dir", "scenes"), sc["default"])
    bg = os.path.join(scene, "settings_bg.rgb.gz")
    if not os.path.exists(bg): bg = os.path.join(scene, "day.rgb.gz")
    img = Image.frombytes("RGB", (W, H), gzip.open(bg).read())
    os.makedirs(os.path.join(d, "splash"), exist_ok=True)
    draw = ImageDraw.Draw(img)
    draw.text((W // 2, H // 2 - 10), meta["name"], font=font(64), fill=IVORY, anchor="ms")
    draw.line((W // 2 - 60, H // 2 + 12, W // 2 + 60, H // 2 + 12), fill=GOLD, width=2)
    f = font(28, 500)
    dots_w = 2 * 13 + 8                                    # (splashanim's three dots, 13 px apart)
    word_w = draw.textlength("Starting", font=f)
    x = (W - word_w - 8 - dots_w) // 2; base = H // 2 + 52
    draw.text((x, base), "Starting", font=f, fill=DIM, anchor="ls")
    open(os.path.join(d, "splash", "dots"), "w").write("%d %d\n" % (x + word_w + 8 + 4, base - 4))
    out = os.path.join(d, "splash", "splash-%dx%dx32-0.raw.gz" % (W, H))
    with gzip.GzipFile(out, "wb", 9, mtime=0) as f: f.write(img.convert("RGBX").tobytes("raw", "BGRX"))
    img.save(os.path.join(d, "splash", "preview.png"))
    print("splash:", os.path.relpath(out, REPO), os.path.getsize(out), "bytes")


def main():
    names = sys.argv[1:] or sorted(n for n in os.listdir(APPS) if os.path.isfile(os.path.join(APPS, n, "app.json"))
                                   and "scene" in json.load(open(os.path.join(APPS, n, "app.json"))))
    for n in names: splash(n)


if __name__ == "__main__":
    main()
