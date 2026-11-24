"""Build the device theme for the Disney Dream from the photograph (the mockup's approach 1).

Reads   assets/dream/panel_photo.jpg, assets/fonts/CormorantGaramond[wght].ttf, and from
        THEME_WORK/mockup (photo_windows.py, run it first): litA.png (the window light, made
        from the photo's own glass) and cellsA.png (which pixels switch together)
Writes  apps/cruise/scenes/dream/ (THEME_OUT), everything ready for the device to load with
        no image decoding beyond zlib:
  day.rgb.gz, dusk.rgb.gz, night.rgb.gz   800x480 raw RGB plates (dusk and night are graded
                                          from the day photo here, with the mockup's formula)
  mask.raw.gz                             800x480 bytes, 255 = ship (water and fireworks stay off it)
  lights.bin.gz                           the window light: which pixels, how much light, which window
  cards.bin.gz                            the flip-clock cards: each digit's top and bottom half, the
                                          card shadow, and the DAYS / DAY label, premultiplied RGBA
  theme.json                              horizon, funnel tops, bow and stern, text position...
  preview.png                             day / dusk / night with every window lit, for a quick look
"""
import gzip, json, os, struct
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "dream"))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "dream"))
OUT = os.environ.get("THEME_OUT", os.path.join(REPO, "apps", "cruise", "scenes", "dream"))
os.makedirs(OUT, exist_ok=True)
W, H = 800, 480

# where things are in the photo (the same numbers as the mockup's panel A)
SCENE = {
    "horizon": 231,
    "stacks": [[180, 156], [300, 142]], "smoke_scale": 0.8,
    "fireworks_scale": 0.85,
    "bow": [638, 370], "stern": [45, 300], "mast": [387, 134],
    "text": [34, 438],
    # the daytime touches: the pennant on the mast, and the AquaDuck tube the raft runs along
    "ambient_scale": 1.0,
    "tube": [[205, 186], [222, 183], [240, 181], [256, 180], [270, 179]],
}
POLY = [(38,302),(40,272),(50,250),(62,212),(110,190),(120,166),(160,163),(163,138),(212,138),(214,158),(268,158),(270,136),(334,136),(336,163),(378,163),(381,130),(397,130),(402,158),(470,160),(485,153),(520,158),(560,178),(576,195),(593,224),(611,261),(719,261),(724,243),(736,254),(776,281),(742,310),(692,350),(642,372),(620,371),(500,362),(400,352),(300,341),(200,329),(100,315),(60,309)]

def save_gz(name, data):
    with gzip.GzipFile(os.path.join(OUT, name), "wb", compresslevel=9, mtime=0) as f: f.write(data)   # (no timestamp: same content, same file)

# The ship sits DY px lower than in the photo, for room above it for the flip clock: the sky band at the
# top (SKY_BAND rows, nothing of the ship in it) is stretched taller and everything below moves down; a
# strip of sea drops off the bottom. (The original photo is gone, so there's no more real sky to use.)
# Everything here that was measured on the photo (outline, windows, positions) moves down with it.
DY, SKY_BAND = 52, 118
def lower(img, resample=Image.LANCZOS):
    out = Image.new(img.mode, (W, H))
    out.paste(img.crop((0, 0, W, SKY_BAND)).resize((W, SKY_BAND + DY), resample), (0, 0))
    out.paste(img.crop((0, SKY_BAND, W, H - DY)), (0, SKY_BAND + DY))
    return out
POLY = [(x, y + DY) for x, y in POLY]
for k in ("stacks", "bow", "stern", "mast", "text", "tube"):
    v = SCENE[k]; SCENE[k] = [[x, y + DY] for x, y in v] if isinstance(v[0], list) else [v[0], v[1] + DY]
SCENE["horizon"] += DY
day = lower(Image.open(os.path.join(ASSETS, "panel_photo.jpg")).convert("RGB").resize((W, H), Image.LANCZOS))
# The photo's own bow wave is frozen white water (and sits in the calm zone under the hull, so the ripple
# never moves it). Paint it out with the sea just below it; the board draws a moving bow wave instead.
def remove_bow_foam(img):
    BX0, BY0, BX1, BY1 = 596, 358 + DY, 706, 390 + DY       # around the bow at the waterline (after lowering)
    px = img.load(); m = Image.new("L", (W, H), 0); mp = m.load()
    inside = Image.new("L", (W, H), 0); ImageDraw.Draw(inside).polygon(POLY, fill=255); ip = inside.load()
    for y in range(BY0, BY1):
        for x in range(BX0, BX1):
            r, g, b = px[x, y]; l = r * 0.3 + g * 0.59 + b * 0.11
            # white-ish water: bright and unsaturated; inside the outline only the last few rows (the foam
            # against the hull), never the red boot-topping or the hull itself
            reach = 7 if x > 628 else 3                         # near the stem the foam climbs a little higher
            near_edge = not ip[x, y] or not ip[x, min(H - 1, y + reach)]
            whiteish = l > 80 and max(r, g, b) - min(r, g, b) < 70
            glow = l > 62 and g > r + 14 and b > r + 14 and not ip[x, y]   # the foam's teal glow in the water
            if (whiteish or glow) and near_edge: mp[x, y] = 255
    m = m.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.5))
    # never over the red boot-topping (the softened edge would nibble its thin tip)
    red = Image.new("L", (W, H), 0); rp = red.load()
    for y in range(BY0 - 4, BY1 + 4):
        for x in range(BX0 - 4, BX1 + 4):
            r, g, b = px[x, y]
            if r > 80 and r > g * 1.5 and r > b * 1.4: rp[x, y] = 255
    m = ImageChops.subtract(m, red.filter(ImageFilter.MaxFilter(3)))
    # fill from open water 90 px to the right, at the same distance from the horizon (same wave size)
    src = img.copy(); src.paste(img.crop((90, 0, W, H)), (0, 0))
    return Image.composite(src, img, m)
day = remove_bow_foam(day)

# ---- dusk and night: the mockup's grade (desaturate, scale the channels, a tint per row)
def lerp(a, b, t): return a + (b - a) * t
def grade(img, n, d):
    hz = SCENE["horizon"]
    out = Image.blend(img, img.convert("L").convert("RGB"), 0.45 * n)
    mr, mg, mb = lerp(1, 0.16, n) * lerp(1, 1.05, d), lerp(1, 0.2, n) * lerp(1, 0.8, d), lerp(1, 0.34, n) * lerp(1, 0.64, d)
    r, g, b = out.split()
    out = Image.merge("RGB", (r.point(lambda v: min(255, int(v * mr + 0.5))), g.point(lambda v: min(255, int(v * mg + 0.5))),
                              b.point(lambda v: min(255, int(v * mb + 0.5)))))
    tint = Image.new("RGB", (W, H)); td = ImageDraw.Draw(tint)
    for y in range(H):
        if y <= hz: k = (y / hz) ** 2.2; c = (d * 95 * k + n * 2, d * 38 * k + n * 5, d * 8 * k + n * 14)
        else: k = (1 - (y - hz) / (H - hz)) ** 6; c = (d * 50 * k, d * 18 * k, 0)
        td.line([(0, y), (W, y)], fill=tuple(int(v + 0.5) for v in c))
    return ImageChops.add(out, tint)
dusk, night = grade(day, 0, 1), grade(day, 1, 0)
def add_stars(img):
    import random
    rnd = random.Random(3); px = img.load(); L = day.convert("L").load(); n = 0
    sky = Image.new("L", (W, H), 0); ImageDraw.Draw(sky).polygon(POLY, fill=255); sp = sky.load()
    while n < 170:
        x, y = rnd.randrange(W), rnd.randrange(SCENE["horizon"] - 6)
        if sp[x, y] or L[x, y] > 215: continue           # not on the ship, not on bright cloud
        a = rnd.random() ** 2 * 0.8 + 0.15; n += 1
        r, g, b = px[x, y]; px[x, y] = (min(255, int(r + 220 * a)), min(255, int(g + 228 * a)), min(255, int(b + 255 * a)))
        if a > 0.7:                                        # the brightest get a soft cross
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                r, g, b = px[x + dx, y + dy]; px[x + dx, y + dy] = (min(255, int(r + 70 * a)), min(255, int(g + 74 * a)), min(255, int(b + 84 * a)))
    return img
night = add_stars(night)
for name, im in (("day", day), ("dusk", dusk), ("night", night)): save_gz(name + ".rgb.gz", im.tobytes())

# the Settings screen's background: the day photo, softly blurred and dimmed
save_gz("settings_bg.rgb.gz", day.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)).tobytes())

ship = Image.new("L", (W, H), 0); ImageDraw.Draw(ship).polygon(POLY, fill=255)
save_gz("mask.raw.gz", ship.tobytes())

# ---- window light, with its glow baked in (the mockup blurs the lights layer live; the board can't)
lit = lower(Image.open(os.path.join(WORK, "mockup", "litA.png")).convert("RGB"))
cells = lower(Image.open(os.path.join(WORK, "mockup", "cellsA.png")).convert("RGB"), Image.NEAREST)
# (a little under the mockup's strength: added to the night plate at full, the mockup's amount runs
# neighbouring cabins together into white bars)
glow = ImageChops.add(lit.filter(ImageFilter.GaussianBlur(2)).point(lambda v: int(v * 0.30)),
                      lit.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.40)))
light = ImageChops.add(lit.point(lambda v: int(v * 0.8)), glow)
# glow pixels belong to the window they came from: spread the window ids outwards a few pixels
cid = Image.new("I", (W, H)); cp = cid.load(); cq = cells.load()
for y in range(H):
    for x in range(W):
        r, g, _ = cq[x, y]; cp[x, y] = r * 256 + g
ids = cid
for _ in range(6): ids = Image.composite(ids, ids.filter(ImageFilter.MaxFilter(3)), ids.point(lambda v: 255 if v else 0).convert("L"))
ip, lp = ids.load(), light.load()
idx, cel, rgb = [], [], bytearray()
for y in range(H):
    for x in range(W):
        r, g, b = lp[x, y]
        if r + g + b >= 9 and ip[x, y]:
            idx.append(y * W + x); cel.append(ip[x, y]); rgb += bytes((r, g, b))
ncell = max(cel) + 1
save_gz("lights.bin.gz", b"VLT1" + struct.pack("<II", len(idx), ncell) + struct.pack("<%dI" % len(idx), *idx)
        + struct.pack("<%dH" % len(cel), *cel) + bytes(rgb))
print("lights: %d pixels in %d windows" % (len(idx), ncell - 1))

# ---- the flip-clock countdown: split-flap cards, top centre above the ship. Each digit is stored as its
# top and bottom half (the board animates the fold between them), plus the card's shadow and the label.
LINING = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")   # make_lining_font.py
CW, CH, SS = 92, 128, 4                      # card size on screen, and the supersampling it's drawn at
# label_gap -1: no DAYS/DAY under the cards (the label images are still stored, for a theme that wants them)
CARDS = {"center_x": 400, "top": 16, "gap": 12, "label_gap": -1}
def premultiplied(img):
    r, g, b, a = img.split()
    return Image.merge("RGBA", tuple(ImageChops.multiply(c, a) for c in (r, g, b)) + (a,)).tobytes()
def card(digit):
    w, h = CW * SS, CH * SS; mid = h // 2
    im = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):                       # top half a little lighter than the bottom, lit from above
        if y < mid: t = y / mid; c = tuple(int(lerp(a_, b_, t)) for a_, b_ in zip((47, 49, 55), (34, 36, 41)))
        else: t = (y - mid) / mid; c = tuple(int(lerp(a_, b_, t)) for a_, b_ in zip((31, 33, 37), (22, 23, 26)))
        d.line([(0, y), (w, y)], fill=c + (255,))
    d.line([(0, 0), (w, 0)], fill=(78, 80, 88, 255), width=SS)                 # light catching the top edge
    f = ImageFont.truetype(LINING, int(CH * 0.97 * SS))
    tb = f.getbbox(str(digit), anchor="ls"); tw, th = tb[2] - tb[0], tb[3] - tb[1]
    txt = Image.new("L", (w, h))                 # centred on the card, so the split runs through the middle
    ImageDraw.Draw(txt).text(((w - tw) / 2 - tb[0], (h + th) / 2), str(digit), font=f, fill=255, anchor="ls")
    ivory = Image.new("RGBA", (w, h), (240, 232, 212, 255))
    shade = Image.new("L", (w, h), 0); ImageDraw.Draw(shade).rectangle([0, mid, w, h], fill=255)
    im = Image.composite(ivory, im, txt)
    im = Image.composite(Image.blend(im, Image.new("RGBA", (w, h), (0, 0, 0, 255)), 0.08), im, shade)   # bottom half in slight shade
    # the split: a dark gap with a faint lit edge below it, and the axle notches at the sides
    d = ImageDraw.Draw(im)
    d.rectangle([0, mid - SS, w, mid + SS - 1], fill=(8, 8, 10, 255))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(52, 54, 60, 255), width=SS // 2)
    for x0 in (0, w - 3 * SS): d.rectangle([x0, mid - 5 * SS, x0 + 3 * SS, mid + 5 * SS], fill=(6, 6, 8, 255))
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=10 * SS, fill=255)
    im.putalpha(mask)
    return im.resize((CW, CH), Image.LANCZOS)
blob = bytearray(b"VFC1") + struct.pack("<HHB", CW, CH, 10)
# the shadow every card casts on the sky
PAD = 14
sh = Image.new("L", (CW + 2 * PAD, CH + 2 * PAD), 0)
ImageDraw.Draw(sh).rounded_rectangle([PAD, PAD + 4, PAD + CW - 1, PAD + CH + 3], radius=10, fill=150)
sh = sh.filter(ImageFilter.GaussianBlur(5))
shadow = Image.merge("RGBA", (*Image.new("RGB", sh.size, (0, 6, 20)).split(), sh))
blob += struct.pack("<hhHH", -PAD, -PAD, shadow.width, shadow.height) + premultiplied(shadow)
for k in range(10):
    c = card(k)
    blob += premultiplied(c.crop((0, 0, CW, CH // 2))) + premultiplied(c.crop((0, CH // 2, CW, CH)))
    if k == 8: c.resize((CW * 3, CH * 3), Image.LANCZOS).save(os.path.join(WORK, "card8.png"))
# "DAYS" / "DAY" under the cards: small spaced capitals with a dark halo so they read against bright sky
def label(text):
    f = ImageFont.truetype(LINING, 21 * SS); sp = 6 * SS; pad = 10 * SS
    w = int(sum(f.getlength(ch) for ch in text) + sp * (len(text) - 1)) + 2 * pad; h = 21 * SS + 2 * pad
    m = Image.new("L", (w, h)); md = ImageDraw.Draw(m); x = pad
    for ch in text: md.text((x, pad + 17 * SS), ch, font=f, fill=255, anchor="ls"); x += f.getlength(ch) + sp
    m = m.resize((w // SS, h // SS), Image.LANCZOS)
    halo = m.filter(ImageFilter.GaussianBlur(3)).point(lambda v: min(255, int(v * 1.6)))
    img = Image.merge("RGBA", (*Image.new("RGB", m.size, (0, 10, 30)).split(), halo.point(lambda v: int(v * 0.55))))
    img = Image.alpha_composite(img, Image.merge("RGBA", (*Image.new("RGB", m.size, (244, 238, 222)).split(), m)))
    return img.crop(img.getbbox())
for text in ("DAYS", "DAY"):
    lb = label(text); blob += struct.pack("<HH", lb.width, lb.height) + premultiplied(lb)
import card_extras                              # "Bon voyage!" and the last day's colon (card_extras.py)
blob += card_extras.extras_blob(CH)
save_gz("cards.bin.gz", bytes(blob))
SCENE["cards"] = CARDS
json.dump(SCENE, open(os.path.join(OUT, "theme.json"), "w"), indent=1)
for old in ("glyphs.bin.gz",):
    if os.path.exists(os.path.join(OUT, old)): os.remove(os.path.join(OUT, old))

# ---- preview
def with_lights(img): return ImageChops.add(img, light)
sheet = Image.new("RGB", (W * 3 + 32, H + 16), (18, 20, 24))
for k, im in enumerate((day, dusk, with_lights(night))): sheet.paste(im, (8 + k * (W + 8), 8))
sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS).save(os.path.join(OUT, "preview.png"))
print("theme ->", OUT, sorted(os.listdir(OUT)))
