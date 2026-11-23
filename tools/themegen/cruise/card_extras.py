"""The flip clock's extras, stored after the DAYS/DAY labels in a theme's cards.bin.gz: the
"Bon voyage!" banner shown in place of the cards once the ship has sailed, and the colon between
the last day's hours and minutes (HH:MM). Premultiplied RGBA, each as width, height (u16) + pixels.

photo_theme.py adds them when it builds a theme; on its own, this adds (or replaces) them in an
existing theme's cards.bin.gz:
    python3 tools/themegen/cruise/card_extras.py vacation/modules/cruise/scenes/dream
"""
import gzip, os, struct, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
LINING = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
IVORY, HALO = (244, 238, 222), (0, 10, 30)
SS = 4


def premultiplied(img):
    r, g, b, a = img.split()
    return Image.merge("RGBA", tuple(ImageChops.multiply(c, a) for c in (r, g, b)) + (a,)).tobytes()


def glowing(mask, halo_blur=5, halo_gain=1.5, halo_alpha=0.6):
    """Ivory shape with a soft dark halo, so it reads against bright sky and dark night alike."""
    halo = mask.filter(ImageFilter.GaussianBlur(halo_blur)).point(lambda v: min(255, int(v * halo_gain)))
    img = Image.merge("RGBA", (*Image.new("RGB", mask.size, HALO).split(), halo.point(lambda v: int(v * halo_alpha))))
    img = Image.alpha_composite(img, Image.merge("RGBA", (*Image.new("RGB", mask.size, IVORY).split(), mask)))
    return img.crop(img.getbbox())


def banner(card_h=128):
    """ "Bon voyage!" about as tall as the cards' digits."""
    size = int(card_h * 0.62); f = ImageFont.truetype(LINING, size * SS); pad = 24 * SS
    text = "Bon voyage!"
    w = int(f.getlength(text)) + 2 * pad; h = int(size * 1.4) * SS + 2 * pad
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text((pad, pad + size * SS), text, font=f, fill=255, anchor="ls")
    return glowing(m.resize((w // SS, h // SS), Image.LANCZOS), 6, 1.6, 0.7)


def colon(card_h=128):
    """Two dots, between the hours and minutes cards."""
    w, h = 22, card_h; r = 6.5; m = Image.new("L", (w * SS, h * SS)); d = ImageDraw.Draw(m)
    for cy in (h * 0.34, h * 0.66):
        d.ellipse(((w / 2 - r) * SS, (cy - r) * SS, (w / 2 + r) * SS, (cy + r) * SS), fill=255)
    return glowing(m.resize((w, h), Image.LANCZOS), 3, 1.6, 0.6)


def extras_blob(card_h=128):
    blob = bytearray()
    for img in (banner(card_h), colon(card_h)):
        blob += struct.pack("<HH", img.width, img.height) + premultiplied(img)
    return bytes(blob)


def add_to(theme_dir):
    """Rewrite theme_dir/cards.bin.gz with these extras (dropping any it already has)."""
    path = os.path.join(theme_dir, "cards.bin.gz"); data = gzip.open(path).read()
    assert data[:4] == b"VFC1", "not a cards file"
    cw, ch = struct.unpack_from("<HH", data, 4); o = 9
    _, _, sw, sh = struct.unpack_from("<hhHH", data, o); o += 8 + sw * sh * 4
    o += 10 * cw * (ch // 2) * 4 * 2
    for _ in range(2):
        lw, lh = struct.unpack_from("<HH", data, o); o += 4 + lw * lh * 4
    with gzip.GzipFile(path, "wb", 9, mtime=0) as f: f.write(data[:o] + extras_blob(ch))
    print("cards: banner and colon ->", path)


if __name__ == "__main__":
    add_to(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "vacation", "modules", "cruise", "scenes", "dream"))
