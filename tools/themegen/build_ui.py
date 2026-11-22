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

os.makedirs(os.path.dirname(OUT), exist_ok=True)
blob = bytearray(b"VUI1") + struct.pack("<H", len(entries))
for name, img, ox, oy, adv in entries:
    blob += name.encode().ljust(64, b"\0") + struct.pack("<HHhhh", img.width, img.height, ox, oy, adv) + img.tobytes()
with gzip.open(OUT, "wb", 9) as f: f.write(bytes(blob))
print("ui: %d images, %d bytes -> %s" % (len(entries), len(blob), OUT))
