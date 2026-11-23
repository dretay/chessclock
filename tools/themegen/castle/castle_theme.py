"""Build the castle module's scene for the device from the renders (scene.py) and the AI detail pass
(ai_detail.py --keep). Pillow only.

    python3 tools/themegen/castle/castle_theme.py [--no-ai]

Reads   THEME_WORK (default tools/themegen/work/castle): ai/{day,dusk,night}.png (or, with --no-ai,
        renders/{day,dusk,night}.png), renders/mask.png (everything that isn't sky), renders/windows.png
        (the windows' glass, white), positions.json
Writes  vacation/modules/castle/scenes/magic-kingdom/ (THEME_OUT), what the drawing library loads:
  day.rgb.gz, dusk.rgb.gz, night.rgb.gz   800x480 raw RGB plates (night with a few stars)
  mask.raw.gz                             800x480 bytes, 255 = not sky (fireworks go behind it)
  lights.bin.gz                           the windows' light: which pixels, how much, which window
  cards.bin.gz                            parchment flip-clock cards, "Have a magical day!", the colon
  settings_bg.rgb.gz                      the Settings screen's background
  theme.json                              horizon, cards, and "effects": [] (no sea, smoke, wake...)
  preview.png                             day / dusk / night with every window lit
"""
import gzip, json, os, random, struct, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "castle"))
OUT = os.environ.get("THEME_OUT", os.path.join(REPO, "vacation", "modules", "castle", "scenes", "magic-kingdom"))
LINING = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
W, H = 800, 480
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(HERE, "..", "cruise")); import card_extras            # (the colon, and the glowing text)


def save_gz(name, data):
    with gzip.GzipFile(os.path.join(OUT, name), "wb", compresslevel=9, mtime=0) as f: f.write(data)   # (no timestamp: same content, same file)


def premultiplied(img):
    r, g, b, a = img.split()
    return Image.merge("RGBA", tuple(ImageChops.multiply(c, a) for c in (r, g, b)) + (a,)).tobytes()


src = "renders" if "--no-ai" in sys.argv else "ai"
plates = {k: Image.open(os.path.join(WORK, src, k + ".png")).convert("RGB").resize((W, H), Image.LANCZOS) for k in ("day", "dusk", "night")}
pos = json.load(open(os.path.join(WORK, "positions.json")))
HORIZON = int(round(pos["horizon"]))

# ---- what isn't sky: the castle, the trees, the lamps (the fireworks are drawn behind them)
notsky = Image.open(os.path.join(WORK, "renders", "mask.png")).getchannel("A").resize((W, H), Image.LANCZOS)
notsky = notsky.point(lambda v: 255 if v > 100 else 0)
notsky.paste(255, (0, HORIZON, W, H))                    # (and everything below the horizon)
save_gz("mask.raw.gz", notsky.tobytes())

# ---- a few stars in the night sky (not on the castle, the trees or the moon's glow)
def add_stars(img, n=120):
    rnd = random.Random(3); px = img.load(); sp = notsky.load(); L = img.convert("L").load(); k = 0
    while k < n:
        x, y = rnd.randrange(W), rnd.randrange(HORIZON - 20)
        if sp[x, y] or L[x, y] > 70: continue
        a = rnd.random() ** 2 * 0.7 + 0.15; k += 1
        r, g, b = px[x, y]; px[x, y] = (min(255, int(r + 210 * a)), min(255, int(g + 218 * a)), min(255, int(b + 240 * a)))
    return img
plates["night"] = add_stars(plates["night"])
for k, im in plates.items(): save_gz(k + ".rgb.gz", im.tobytes())
save_gz("settings_bg.rgb.gz", plates["day"].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)).tobytes())

# ---- the windows' light: only the glass (the mask is the render's, at its full size, shrunk a pixel so
# frames and tracery stay stone), warm amber, added onto the night plate's dark glass, with a faint
# glow; each window (a connected patch of glass) switches as one
glass = Image.open(os.path.join(WORK, "renders", "windows.png")).convert("L").point(lambda v: 255 if v > 128 else 0)
glass = glass.filter(ImageFilter.MinFilter(3))
cover = glass.resize((W, H), Image.BOX)                  # how much of each screen pixel is glass
cp = cover.load()
cell = [[0] * W for _ in range(H)]; ncell = 1; sizes = {}
for y in range(H):
    for x in range(W):
        if cp[x, y] > 90 and not cell[y][x]:
            stack, pts = [(y, x)], []; cell[y][x] = ncell
            while stack:
                cy, cx = stack.pop(); pts.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < H and 0 <= xx < W and cp[xx, yy] > 90 and not cell[yy][xx]: cell[yy][xx] = ncell; stack.append((yy, xx))
            if len(pts) < 4:                             # (specks along railings and the like: not windows)
                for cy, cx in pts: cell[cy][cx] = -1
            else: sizes[ncell] = len(pts); ncell += 1
AMBER = (255, 168, 80)
lit = Image.new("RGB", (W, H)); lp = lit.load()
for y in range(H):
    for x in range(W):
        if cell[y][x] > 0:
            a = cp[x, y] / 255 * 0.85; lp[x, y] = tuple(int(c * a) for c in AMBER)
light = ImageChops.add(lit, lit.filter(ImageFilter.GaussianBlur(2.5)).point(lambda v: int(v * 0.35)))
# glow pixels belong to the window they came from: spread the ids a few pixels
ids = Image.new("I", (W, H)); ip = ids.load()
for y in range(H):
    for x in range(W):
        if cell[y][x] > 0: ip[x, y] = cell[y][x]
for _ in range(4): ids = Image.composite(ids, ids.filter(ImageFilter.MaxFilter(3)), ids.point(lambda v: 255 if v else 0).convert("L"))
ip, lp = ids.load(), light.load()
idx, cel, rgb = [], [], bytearray()
for y in range(H):
    for x in range(W):
        r, g, b = lp[x, y]
        if r + g + b >= 9 and ip[x, y]:
            idx.append(y * W + x); cel.append(ip[x, y]); rgb += bytes((r, g, b))
save_gz("lights.bin.gz", b"VLT1" + struct.pack("<II", len(idx), ncell) + struct.pack("<%dI" % len(idx), *idx)
        + struct.pack("<%dH" % len(cel), *cel) + bytes(rgb))
print("lights: %d pixels in %d windows" % (len(idx), ncell - 1))

# ---- the cards: parchment, ink digits; the same layout as the ship's (cards.bin.gz, VFC1)
CW, CH, SS = 138, 192, 3          # (half as big again as the ship's: the castle's sky has room)
PAPER, INK = (236, 224, 196), (58, 36, 22)
def parchment(w, h, seed):
    """Cream paper: fine grain, a few soft blotches and fibres, edges darker with age."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), PAPER)
    grain = Image.effect_noise((w, h), 22).filter(ImageFilter.GaussianBlur(0.8))           # around 128
    blot = Image.effect_noise((w // 24 + 1, h // 24 + 1), 40).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(10 * SS // 4))
    def shade(img, m, k):          # darken img where the noise m is low, by up to k
        f = m.point(lambda v: int(255 * (1 - k) + k * v)); return ImageChops.multiply(img, Image.merge("RGB", (f, f, f)))
    im = shade(im, grain, 0.07); im = shade(im, blot, 0.10)
    d = ImageDraw.Draw(im)
    for _ in range(60):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h); dx, dy = rnd.uniform(-9, 9) * SS, rnd.uniform(-3, 3) * SS
        c = rnd.randint(195, 215); d.line([(x, y), (x + dx, y + dy)], fill=(c, c - 14, c - 38), width=max(1, SS // 3))
    edge = Image.new("L", (w, h), 0); ImageDraw.Draw(edge).rounded_rectangle([0, 0, w - 1, h - 1], 10 * SS, outline=255, width=7 * SS)
    edge = edge.filter(ImageFilter.GaussianBlur(5 * SS))
    return Image.composite(ImageChops.multiply(im, Image.new("RGB", (w, h), (196, 182, 160))), im, edge)
def card(digit):
    w, h = CW * SS, CH * SS; mid = h // 2
    im = parchment(w, h, 11 + digit)
    shade = Image.new("L", (w, h), 0); ImageDraw.Draw(shade).rectangle([0, mid, w, h], fill=22)   # the bottom half in slight shade
    im = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, shade)
    f = ImageFont.truetype(LINING, int(CH * 0.97 * SS))
    tb = f.getbbox(str(digit), anchor="ls"); tw, th = tb[2] - tb[0], tb[3] - tb[1]
    txt = Image.new("L", (w, h)); ImageDraw.Draw(txt).text(((w - tw) / 2 - tb[0], (h + th) / 2), str(digit), font=f, fill=255, anchor="ls")
    im = Image.composite(Image.new("RGB", (w, h), INK), im, txt)
    d = ImageDraw.Draw(im)                              # the fold: a thin dark gap, a light edge below it
    d.rectangle([0, mid - SS // 2, w, mid + SS // 2], fill=(120, 98, 70))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(250, 242, 222), width=SS // 2)
    for x0 in (0, w - 4 * SS): d.rectangle([x0, mid - 7 * SS, x0 + 4 * SS, mid + 7 * SS], fill=(92, 72, 50))
    out = im.convert("RGBA")
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=14 * SS, fill=255)
    out.putalpha(mask)
    return out.resize((CW, CH), Image.LANCZOS)
blob = bytearray(b"VFC1") + struct.pack("<HHB", CW, CH, 10)
PAD = 18
sh = Image.new("L", (CW + 2 * PAD, CH + 2 * PAD), 0)
ImageDraw.Draw(sh).rounded_rectangle([PAD, PAD + 6, PAD + CW - 1, PAD + CH + 5], radius=14, fill=160)
sh = sh.filter(ImageFilter.GaussianBlur(7))
shadow = Image.merge("RGBA", (*Image.new("RGB", sh.size, (0, 4, 14)).split(), sh))
blob += struct.pack("<hhHH", -PAD, -PAD, shadow.width, shadow.height) + premultiplied(shadow)
for k in range(10):
    c = card(k)
    blob += premultiplied(c.crop((0, 0, CW, CH // 2))) + premultiplied(c.crop((0, CH // 2, CW, CH)))
    if k == 8: c.resize((CW * 3, CH * 3), Image.LANCZOS).save(os.path.join(WORK, "card8.png"))
for text in ("DAYS", "DAY"):                            # (stored, as the format wants; not shown: label_gap -1)
    lb = Image.new("RGBA", (1, 1)); blob += struct.pack("<HH", 1, 1) + premultiplied(lb)
def banner(text="Have a magical day!"):
    size = 64; f = ImageFont.truetype(LINING, size * SS); pad = 24 * SS             # (not from the cards: they're big)
    w = int(f.getlength(text)) + 2 * pad; h = int(size * 1.4) * SS + 2 * pad
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text((pad, pad + size * SS), text, font=f, fill=255, anchor="ls")
    return card_extras.glowing(m.resize((w // SS, h // SS), Image.LANCZOS), 6, 1.6, 0.7)
for img in (banner(), card_extras.colon(CH)):
    blob += struct.pack("<HH", img.width, img.height) + premultiplied(img)
save_gz("cards.bin.gz", bytes(blob))

# ---- for the drawing library (vacation.py reads it): none of the ship's effects (no sea, smoke, wake...),
# so none of the ship's places either; the horizon is where the fireworks go up from
scene = {
    "effects": [],
    "horizon": HORIZON,
    "fireworks_scale": 0.85,
    "cards": {"center_x": 170, "top": 16, "gap": 12, "label_gap": -1},
}
json.dump(scene, open(os.path.join(OUT, "theme.json"), "w"), indent=1)

sheet = Image.new("RGB", (W * 3 + 32, H + 16), (18, 20, 24))
for k, im in enumerate((plates["day"], plates["dusk"], ImageChops.add(plates["night"], light))): sheet.paste(im, (8 + k * (W + 8), 8))
sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS).save(os.path.join(OUT, "preview.png"))
print("scene ->", OUT, sorted(os.listdir(OUT)))
