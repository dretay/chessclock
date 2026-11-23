"""Draw the Settings pages' text and arrows on a desktop, for the board to place without Pillow.

    python3 tools/themegen/build_ui.py      -> vacation/ui/ui.bin.gz

Every string in vacation/vacation_layout.py's STRINGS (and the digits 0-9 in the fonts that show
numbers) becomes an antialiased alpha image, with its offset from the pen position on the
baseline and its advance, so the board can colour it and line it up. Plus the spinner arrows.
Needs assets/fonts/CormorantGaramond-SemiBold-Lining.ttf (make_lining_font.py).

File: "VUI1", count (u16), then per image: name (64 bytes, utf-8, zero padded), w, h (u16),
ox, oy, advance (i16), w*h alpha bytes.
"""
import gzip, os, struct, sys
from PIL import Image, ImageDraw, ImageFont

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "vacation"))
import vacation_layout as L

FONT = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
OUT = os.path.join(REPO, "vacation", "ui", "ui.bin.gz")

entries = []
def add(name, img, ox=0, oy=0, adv=0):
    assert len(name.encode()) <= 63, name
    entries.append((name, img, ox, oy, adv))

def text(font_name, s):
    f = ImageFont.truetype(FONT, L.FONTS[font_name])
    pad = 20; w = int(f.getlength(s)) + 2 * pad; h = L.FONTS[font_name] * 2 + 2 * pad; base = pad + L.FONTS[font_name]
    im = Image.new("L", (w, h)); ImageDraw.Draw(im).text((pad, base), s, font=f, fill=255, anchor="ls")
    bb = im.getbbox() or (pad, base, pad + 1, base + 1)
    add("%s|%s" % (font_name, s), im.crop(bb), bb[0] - pad, bb[1] - base, int(round(f.getlength(s))))

for font_name, strings in L.STRINGS.items():
    for s in strings: text(font_name, s)
for font_name in L.DIGIT_FONTS:
    for d in "0123456789": text(font_name, d)
for font_name in L.CHAR_FONTS:
    for ch in [chr(c) for c in range(32, 127)] + list(L.EXTRA_CHARS):
        if ch not in "0123456789" and "%s|%s" % (font_name, ch) not in {e[0] for e in entries}: text(font_name, ch)

# spinner arrows (drawn at 4x and shrunk, for smooth edges)
for name, pts in (("arrow|up", [(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)]), ("arrow|down", [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)])):
    S = 4; w, h = 26, 14
    im = Image.new("L", (w * S, h * S)); ImageDraw.Draw(im).polygon([(x * w * S, y * h * S) for x, y in pts], fill=255)
    add(name, im.resize((w, h), Image.LANCZOS))
# the calibration cross
S = 4; im = Image.new("L", (48 * S, 48 * S)); d = ImageDraw.Draw(im)
d.line((2 * S, 24 * S, 46 * S, 24 * S), fill=255, width=2 * S); d.line((24 * S, 2 * S, 24 * S, 46 * S), fill=255, width=2 * S)
d.ellipse((13 * S, 13 * S, 35 * S, 35 * S), outline=255, width=2 * S)
add("cross", im.resize((48, 48), Image.LANCZOS), -24, -24)

# the fleet map's ships: a cruise ship seen from above, bow up, at every 15 degrees of heading.
# "boat|s|k" the hull and decks, "boatf|s|k" its two funnels (drawn red), "boath|s|k" a halo round it;
# s is the size (s small, l large: the ship the map follows), k the heading / 15.
def boat_layers(L, B, S=6):
    n = int(L * 1.5) + 8; c = n * S / 2
    def P(x, y): return (c + x * S, c + y * S)
    hull = Image.new("L", (n * S, n * S)); d = ImageDraw.Draw(hull)
    pts = []
    for i in range(13):                                    # the bow: a pointed curve
        t = i / 12; pts.append((B / 2 * (1 - (1 - t) ** 2.2), -L / 2 + t * 0.36 * L))
    pts += [(B / 2, L / 2 - B * 0.18), (B * 0.36, L / 2)]  # straight sides, a squared-off stern
    d.polygon([P(x, y) for x, y in pts] + [P(-x, y) for x, y in reversed(pts)], fill=255)
    fun = Image.new("L", hull.size); fd = ImageDraw.Draw(fun); r = B * 0.19
    for fy in (0.0 * L, 0.2 * L):
        x0, y0 = P(-r, fy - r); x1, y1 = P(r, fy + r); fd.ellipse((x0, y0, x1, y1), fill=255)
    halo = hull.filter(ImageFilter.MaxFilter(2 * int(1.2 * S) + 1)).filter(ImageFilter.GaussianBlur(S * 0.7))
    return hull, fun, halo, n
from PIL import ImageFilter
for size, L_, B_ in (("s", 24, 7), ("l", 34, 10)):
    hull, fun, halo, n = boat_layers(L_, B_)
    for k in range(24):
        for kind, im in (("boat", hull), ("boatf", fun), ("boath", halo)):
            r = im.rotate(-15 * k, resample=Image.BICUBIC).resize((n, n), Image.LANCZOS)
            if kind == "boath": r = r.point(lambda v: min(255, v * 2))
            bb = r.getbbox() or (0, 0, 1, 1)                  # just the part with something in it
            add("%s|%s|%d" % (kind, size, k), r.crop(bb), bb[0] - n // 2, bb[1] - n // 2)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
blob = bytearray(b"VUI1") + struct.pack("<H", len(entries))
for name, img, ox, oy, adv in entries:
    blob += name.encode().ljust(64, b"\0") + struct.pack("<HHhhh", img.width, img.height, ox, oy, adv) + img.tobytes()
with gzip.GzipFile(OUT, "wb", 9, mtime=0) as f: f.write(bytes(blob))   # (no timestamp: same content, same file)
print("ui: %d images, %d bytes -> %s" % (len(entries), len(blob), OUT))
