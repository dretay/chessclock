#!/usr/bin/env python3
"""Pack a scene's pictures into what the device's drawing library loads: any countdown app's scene.
Pillow only.

    python3 tools/themegen/scene_pack.py WORK OUT [--greeting TEXT] [--horizon Y] [--no-stars]

WORK (a folder of pictures, any size: they're scaled to 800x480; the same camera for all):
    day.png, dusk.png, night.png   the plates, blended by time of day
    mask.png       optional: white (or opaque) where it isn't sky: the subject, trees, ground
                   (fireworks go up behind it, stars stay off it); without it, all sky above the horizon
    windows.png    optional: white where there's glass that lights up at night (each connected patch
                   switches on and off as one window); without it, no window lights. (Painted in the
                   previewer's Scene Builder: scene.json "windows_painted": true, so it isn't thinned)
    scene.json     optional: {"horizon": y (screen pixels, 0-480: where fireworks go up from, and below
                   which is never sky), "greeting": "Have a magical day!", "cards": {...}, "card_style":
                   "parchment" (cream paper, ink digits), "black" (split-flap: dark, ivory digits), "wood" (a
                   trail sign: routed cream digits in a board) or "board" (a station's departure board:
                   matte black, condensed white digits),
                   "fireworks_scale": 0.85, "light": [r, g, b],
                   "orb": {"cx": x, "cy": y, "r": radius, "spacing": px (default: about 500 lights)}: a sphere's coloured night
                   lights (the "twinkle" effect: EPCOT's Spaceship Earth), spread over its visible half,
                   in screen pixels; "effects": ["twinkle"];
                   "show": {"program": ["spin", "wash", ...], "secs": 12}: the lights' show, its patterns
                   in turn, each that long, crossfading (waves, rings, blink, spin, rise, wash, sparkle,
                   spiral, comet, heartbeat; without it, all of them)} (the command line overrides it)
    twinkle_mask.png  optional, with "orb": white where the lights show (paint out what's in front of
                   the sphere: trees, its legs); without it, the whole circle
    scene.json "smoke": {"points": [[x, y], ...], "scale": 0.8, "wind": 0 (-1 left .. 1 right), "rate": 4}:
                   smoke rising from those points (a campfire, a chimney: up to 8); "birds": true: now and
                   then a few birds cross the sky, by day; "foam": {"points": [[x, y, r], ...], "amount": 1.0,
                   "flow": "still" | "left" | "right" | "falling" | "toward"}: white water at those points
                   (on the scene's water, if it has some)
    water.png      optional: white where there's water: it ripples ("water" effect; scene.json "water":
                   {"strength": 1.0, "speed": 1.0}; painted or found in the previewer's Scene Builder)
    twinkle_points.json  optional, with "orb": the lights' places, [[x, y], ...] (photo_scene.py finds
                   them on the photo's panels); without it, spread over a sphere
OUT (the app's scenes/<name>/):
    day.rgb.gz, dusk.rgb.gz, night.rgb.gz, mask.raw.gz, lights.bin.gz, cards.bin.gz (parchment flip
    cards, the greeting, the colon), settings_bg.rgb.gz, theme.json, preview.png
"""
import argparse, gzip, json, os, random, struct, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
LINING = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
W, H = 800, 480
import card_extras                                                     # (the colon, and the glowing text: beside this file)
CARDS = {"center_x": 170, "top": 16, "gap": 12, "label_gap": -1, "scale3": 0.82}   # (top left, clear of a central subject)


def premultiplied(img):
    r, g, b, a = img.split()
    return Image.merge("RGBA", tuple(ImageChops.multiply(c, a) for c in (r, g, b)) + (a,)).tobytes()


class Out:
    def __init__(self, path): self.path = path; os.makedirs(path, exist_ok=True)
    def gz(self, name, data):
        with gzip.GzipFile(os.path.join(self.path, name), "wb", compresslevel=9, mtime=0) as f: f.write(data)   # (same content, same file)


def add_stars(img, notsky, horizon, n=120):
    """A few stars in the night sky (not on the subject, nor where the sky is already bright)."""
    rnd = random.Random(3); px = img.load(); sp = notsky.load(); lum = img.convert("L").load(); k = tries = 0
    while k < n and tries < n * 400:                     # (a picture with little or no dark sky: as many as fit)
        tries += 1
        x, y = rnd.randrange(W), rnd.randrange(max(1, horizon - 20))
        if sp[x, y] or lum[x, y] > 70: continue
        a = rnd.random() ** 2 * 0.7 + 0.15; k += 1
        r, g, b = px[x, y]; px[x, y] = (min(255, int(r + 210 * a)), min(255, int(g + 218 * a)), min(255, int(b + 240 * a)))
    return img


NEAR, WIDE = (1.5, 0.5), (4, 0.4)                                      # painted windows' glow: (blur, strength) close by, and wide


def window_groups(work):
    """window_groups.json (the Group tool's boxes: the windows each touches switch as one), or []."""
    try: return json.load(open(os.path.join(work, "window_groups.json")))
    except (OSError, ValueError): return []


def lights_picture(blob):
    """(the light picture, how many windows) from a lights.bin.gz's contents (VLT1)."""
    nl, nc = struct.unpack("<II", blob[4:12])
    idx = struct.unpack("<%dI" % nl, blob[12:12 + 4 * nl]); rgb = blob[12 + 6 * nl:12 + 9 * nl]
    img = Image.new("RGB", (W, H)); px = img.load()
    for k, i in enumerate(idx): px[i % W, i // W] = tuple(rgb[3 * k:3 * k + 3])
    return img, nc - 1


def frame_picture(work):
    """window_frame.png (the Frame brush's strokes: what stays dark in front of a window's light), or None."""
    p = os.path.join(work, "window_frame.png")
    return Image.open(p).convert("L").resize((W, H)) if os.path.exists(p) else None


def painted_light(cover, ids, ncell, colour, frame=None):
    """Windows painted by hand, lit like real ones: a soft edge, brighter in the middle (a lamp inside, not
    a flat panel), each window its own lamp (a little brighter or dimmer, warmer or whiter), and its light
    spilling onto the stone round it: a close glow and a wide faint one."""
    # frame (window_frame.png, painted with the Frame brush: a lantern's bars, mullions, leading): in front of
    # the light, so dark, and its glow doesn't light them either
    open_ = ImageChops.invert(frame.filter(ImageFilter.GaussianBlur(0.9))) if frame is not None else None
    soft = cover.filter(ImageFilter.GaussianBlur(0.7))
    if open_ is not None: soft = ImageChops.multiply(soft, open_)
    sp = soft.load()
    core = cover.filter(ImageFilter.GaussianBlur(1.6)); kp = core.load()
    ip = ids.load()
    peak = [1] * (ncell + 1)
    for y in range(H):
        for x in range(W):
            c = ip[x, y]
            if c > 0 and kp[x, y] > peak[c]: peak[c] = kp[x, y]
    rng = random.Random(7)                                              # (the same lamps each time it's packed)
    lamp = [(rng.uniform(0.7, 1.05), rng.uniform(0.0, 0.6)) for _ in range(ncell + 1)]
    warm = (255, 205, 135)
    lit = Image.new("RGB", (W, H)); lp = lit.load()
    for y in range(H):
        for x in range(W):
            c = ip[x, y]
            if c <= 0 or sp[x, y] < 6: continue
            bright, w = lamp[c]
            a = sp[x, y] / 255 * (0.45 + 0.55 * min(1.0, kp[x, y] / peak[c])) * 0.95 * bright
            lp[x, y] = tuple(int((k + (q - k) * w) * a) for k, q in zip(colour, warm))
    # (the glow from each window's brightness, not its amount of light: a small window glows as much as a big one)
    near = lit.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(NEAR[0])).point(lambda v: int(v * NEAR[1]))
    wide = lit.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(WIDE[0])).point(lambda v: int(v * WIDE[1]))
    light = ImageChops.add(ImageChops.add(lit, near), wide)
    if open_ is not None:                                                # (a frame catches only a little of the glow behind it)
        keep = open_.point(lambda v: 40 + v * 215 // 255)
        light = ImageChops.multiply(light, Image.merge("RGB", (keep,) * 3))
    return light


def window_lights(glass, colour, thin=True, frame=None, groups=()):
    """lights.bin.gz's contents (VLT1): each lit pixel, its light, and its window; and the light picture.
    thin: the glass shrunk a pixel first (a render's mask: frames and tracery stay dark); not for windows
    painted by hand (small ones would vanish)."""
    glass = glass.convert("L").point(lambda v: 255 if v > 128 else 0)
    if thin: glass = glass.filter(ImageFilter.MinFilter(3))
    cover = glass.resize((W, H), Image.BOX); cp = cover.load()           # how much of each screen pixel is glass
    cell = [[0] * W for _ in range(H)]; ncell = 1
    for y in range(H):
        for x in range(W):
            if cp[x, y] > 90 and not cell[y][x]:
                stack, pts = [(y, x)], []; cell[y][x] = ncell
                while stack:
                    cy, cx = stack.pop(); pts.append((cy, cx))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = cy + dy, cx + dx
                        if 0 <= yy < H and 0 <= xx < W and cp[xx, yy] > 90 and not cell[yy][xx]: cell[yy][xx] = ncell; stack.append((yy, xx))
                if len(pts) < 4:                                     # (specks: not windows)
                    for cy, cx in pts: cell[cy][cx] = -1
                else: ncell += 1
    if groups:                                                           # (grouped: every window a box touches, one light)
        parent = list(range(ncell))
        def root(c):
            while parent[c] != c: parent[c] = parent[parent[c]]; c = parent[c]
            return c
        for x0, y0, x1, y1 in groups:
            x0, x1 = sorted((max(0, int(x0)), min(W - 1, int(x1)))); y0, y1 = sorted((max(0, int(y0)), min(H - 1, int(y1))))
            inside = {cell[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if cell[y][x] > 0}
            if len(inside) > 1:
                first = root(min(inside))
                for c in inside: parent[root(c)] = first
        renum, k = {}, 1
        for c in range(1, ncell):
            r = root(c)
            if r not in renum: renum[r] = k; k += 1
        for y in range(H):
            row = cell[y]
            for x in range(W):
                if row[x] > 0: row[x] = renum[root(row[x])]
        ncell = k
    ids = Image.new("I", (W, H)); ip = ids.load()                       # glow pixels belong to their window
    for y in range(H):
        for x in range(W):
            if cell[y][x] > 0: ip[x, y] = cell[y][x]
    for _ in range(4 if thin else 9):
        # (which pixels have a window: for painted ones, as an L picture; point() on an "I" picture is only
        # ever a scale and offset, so the render's windows have never had their glow, and are kept as they look)
        has = ids.point(lambda v: 255 if v else 0).convert("L") if thin else ids.convert("L").point(lambda v: 255 if v else 0)
        ids = Image.composite(ids, ids.filter(ImageFilter.MaxFilter(3)), has)
    if thin:                                                            # (a render's windows: tiny panes, seen from afar)
        lit = Image.new("RGB", (W, H)); lp = lit.load()
        for y in range(H):
            for x in range(W):
                if cell[y][x] > 0: a = cp[x, y] / 255 * 0.85; lp[x, y] = tuple(int(c * a) for c in colour)
        light = ImageChops.add(lit, lit.filter(ImageFilter.GaussianBlur(2.5)).point(lambda v: int(v * 0.35)))
    else: light = painted_light(cover, ids, ncell, colour, frame)

    ip, lp = ids.load(), light.load()
    idx, cel, rgb = [], [], bytearray()
    for y in range(H):
        for x in range(W):
            r, g, b = lp[x, y]
            if r + g + b >= 9 and ip[x, y]: idx.append(y * W + x); cel.append(ip[x, y]); rgb += bytes((r, g, b))
    blob = b"VLT1" + struct.pack("<II", len(idx), ncell) + struct.pack("<%dI" % len(idx), *idx) + struct.pack("<%dH" % len(cel), *cel) + bytes(rgb)
    return blob, light, ncell - 1


# ---- the cards: parchment, ink digits (cards.bin.gz, VFC1)
CW, CH, SS = 138, 192, 3
PAPER, INK = (236, 224, 196), (58, 36, 22)


def parchment(w, h, seed):
    """Cream paper: fine grain, a few soft blotches and fibres, edges darker with age."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), PAPER)
    grain = Image.effect_noise((w, h), 22).filter(ImageFilter.GaussianBlur(0.8))
    blot = Image.effect_noise((w // 24 + 1, h // 24 + 1), 40).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(10 * SS // 4))
    def shade(img, m, k):
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
    shade = Image.new("L", (w, h), 0); ImageDraw.Draw(shade).rectangle([0, mid, w, h], fill=22)
    im = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, shade)
    f = ImageFont.truetype(LINING, int(CH * 0.97 * SS))
    tb = f.getbbox(str(digit), anchor="ls"); tw, th = tb[2] - tb[0], tb[3] - tb[1]
    txt = Image.new("L", (w, h)); ImageDraw.Draw(txt).text(((w - tw) / 2 - tb[0], (h + th) / 2), str(digit), font=f, fill=255, anchor="ls")
    im = Image.composite(Image.new("RGB", (w, h), INK), im, txt)
    d = ImageDraw.Draw(im)                                  # the fold
    d.rectangle([0, mid - SS // 2, w, mid + SS // 2], fill=(120, 98, 70))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(250, 242, 222), width=SS // 2)
    for x0 in (0, w - 4 * SS): d.rectangle([x0, mid - 7 * SS, x0 + 4 * SS, mid + 7 * SS], fill=(92, 72, 50))
    out = im.convert("RGBA")
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=14 * SS, fill=255)
    out.putalpha(mask)
    return out.resize((CW, CH), Image.LANCZOS)


def card_black(digit):
    """A split-flap card: dark grey, lit from above, ivory digits (the cruise's look, at this size)."""
    w, h = CW * SS, CH * SS; mid = h // 2
    def lerp(a, b, t): return a + (b - a) * t
    im = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):                       # (the top half a little lighter than the bottom)
        if y < mid: t = y / mid; c = tuple(int(lerp(a_, b_, t)) for a_, b_ in zip((47, 49, 55), (34, 36, 41)))
        else: t = (y - mid) / mid; c = tuple(int(lerp(a_, b_, t)) for a_, b_ in zip((31, 33, 37), (22, 23, 26)))
        d.line([(0, y), (w, y)], fill=c + (255,))
    d.line([(0, 0), (w, 0)], fill=(78, 80, 88, 255), width=SS)                 # (light catching the top edge)
    f = ImageFont.truetype(LINING, int(CH * 0.97 * SS))
    tb = f.getbbox(str(digit), anchor="ls"); tw, th = tb[2] - tb[0], tb[3] - tb[1]
    txt = Image.new("L", (w, h))
    ImageDraw.Draw(txt).text(((w - tw) / 2 - tb[0], (h + th) / 2), str(digit), font=f, fill=255, anchor="ls")
    shade = Image.new("L", (w, h), 0); ImageDraw.Draw(shade).rectangle([0, mid, w, h], fill=255)
    im = Image.composite(Image.new("RGBA", (w, h), (240, 232, 212, 255)), im, txt)
    im = Image.composite(Image.blend(im, Image.new("RGBA", (w, h), (0, 0, 0, 255)), 0.08), im, shade)
    d = ImageDraw.Draw(im)                   # (the split: a dark gap, a faint lit edge below, the axle notches)
    d.rectangle([0, mid - SS, w, mid + SS - 1], fill=(8, 8, 10, 255))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(52, 54, 60, 255), width=SS // 2)
    for x0 in (0, w - 4 * SS): d.rectangle([x0, mid - 7 * SS, x0 + 4 * SS, mid + 7 * SS], fill=(6, 6, 8, 255))
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=14 * SS, fill=255)
    im.putalpha(mask)
    return im.resize((CW, CH), Image.LANCZOS)


SANS = os.path.join(REPO, "assets", "fonts", "BarlowCondensed-SemiBold.ttf")    # (Google Fonts, OFL: the departure board's)
SLAB = os.path.join(REPO, "assets", "fonts", "Arvo-Bold.ttf")                   # (Google Fonts, OFL: the trail sign's)


def digit_mask(digit, font_path, height_frac, w, h, dy=0):
    """The digit, white on black, its figure height_frac of the card's height, centred (dy: moved down)."""
    size = int(h * height_frac)
    f = ImageFont.truetype(font_path, size)
    tb = f.getbbox("8", anchor="ls"); size = int(size * h * height_frac / (tb[3] - tb[1]))   # (the figure's own height, not the font's)
    f = ImageFont.truetype(font_path, size)
    tb = f.getbbox(str(digit), anchor="ls"); tw, th = tb[2] - tb[0], tb[3] - tb[1]
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text(((w - tw) / 2 - tb[0], (h + th) / 2 + dy), str(digit), font=f, fill=255, anchor="ls")
    return m


def rounded(im, radius):
    mask = Image.new("L", im.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    out = im.convert("RGBA"); out.putalpha(mask); return out


def card_wood(digit):
    """A trail sign: a warm wooden board (grain running across, a little lighter on top), the digit routed
    into it and painted cream: its edges cut in (shadow above, light below), the fold a dark saw cut."""
    w, h = CW * SS, CH * SS; mid = h // 2
    rnd = random.Random(31 + digit)
    grain = Image.effect_noise((w // 6, h * 2), 60).resize((w * 4, h), Image.BICUBIC).crop((0, 0, w, h))   # (streaks across)
    grain = grain.filter(ImageFilter.GaussianBlur(SS * 0.6))
    rings = Image.new("L", (w, h), 128); d = ImageDraw.Draw(rings)
    for _ in range(22):                                                  # (long darker growth lines)
        y = rnd.uniform(0, h); a = rnd.uniform(-6, 6) * SS
        d.line([(0, y), (w / 2, y + a), (w, y + rnd.uniform(-4, 4) * SS)], fill=rnd.randint(70, 105), width=max(1, SS))
    rings = rings.filter(ImageFilter.GaussianBlur(SS * 1.2))
    base = Image.new("RGB", (w, h), (126, 82, 48))
    def tone(img, m, k):
        f = m.point(lambda v: int(255 * (1 - k) + k * v)); return ImageChops.multiply(img, Image.merge("RGB", (f, f, f)))
    im = tone(tone(base, grain, 0.42), rings, 0.62)
    light = Image.new("L", (w, h)); ld = ImageDraw.Draw(light)
    for y in range(h): ld.line([(0, y), (w, y)], fill=int(40 * (1 - y / h)))
    im = ImageChops.add(im, Image.merge("RGB", (light, light, light)))
    m = digit_mask(digit, SLAB, 0.66, w, h, dy=SS)
    cut = m.filter(ImageFilter.MaxFilter(2 * (SS // 2) + 1))            # (the routed groove, a little wider than the paint)
    sh = ImageChops.offset(cut, 0, SS).filter(ImageFilter.GaussianBlur(SS * 0.8))
    hi = ImageChops.subtract(ImageChops.offset(cut, 0, -SS), cut).filter(ImageFilter.GaussianBlur(SS * 0.5))
    im = Image.composite(Image.new("RGB", (w, h), (52, 32, 18)), im, cut)                     # (the groove, dark)
    im = Image.composite(Image.new("RGB", (w, h), (238, 222, 180)), im, m.filter(ImageFilter.GaussianBlur(SS * 0.3)))   # (cream paint)
    im = Image.composite(Image.new("RGB", (w, h), (40, 24, 12)), im, ImageChops.multiply(sh, ImageChops.invert(cut)).point(lambda v: v // 2))
    im = ImageChops.add(im, Image.merge("RGB", (hi.point(lambda v: v // 3),) * 3))
    d = ImageDraw.Draw(im)                                               # (the fold: a saw cut, its lower edge lit)
    d.rectangle([0, mid - SS, w, mid + SS - 1], fill=(36, 22, 12))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(168, 120, 78), width=SS // 2)
    for x0 in (0, w - 4 * SS): d.rectangle([x0, mid - 7 * SS, x0 + 4 * SS, mid + 7 * SS], fill=(30, 18, 10))
    edge = Image.new("L", (w, h), 0); ImageDraw.Draw(edge).rounded_rectangle([0, 0, w - 1, h - 1], 8 * SS, outline=255, width=4 * SS)
    im = Image.composite(ImageChops.multiply(im, Image.new("RGB", (w, h), (170, 150, 135))), im, edge.filter(ImageFilter.GaussianBlur(3 * SS)))
    return rounded(im, 8 * SS).resize((CW, CH), Image.LANCZOS)


def card_board(digit):
    """A station's departure board: a matte black flap, a little lighter at its top, crisp off-white
    condensed digits, a hairline gap at the fold and the hinge pins at its ends."""
    w, h = CW * SS, CH * SS; mid = h // 2
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):
        t = (y % mid) / mid; top = y < mid
        c = int((34 if top else 26) - (8 if top else 6) * t); d.line([(0, y), (w, y)], fill=(c, c, c + 2))
    im = Image.composite(Image.new("RGB", (w, h), (238, 236, 226)), im, digit_mask(digit, SANS, 0.70, w, h))
    shade = Image.new("L", (w, h), 0); ImageDraw.Draw(shade).rectangle([0, mid, w, h], fill=26)
    im = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, shade)    # (the lower flap a touch darker)
    d = ImageDraw.Draw(im)
    d.rectangle([0, mid - SS // 2 - 1, w, mid + SS // 2], fill=(4, 4, 5))
    d.line([(0, mid + SS), (w, mid + SS)], fill=(58, 58, 62), width=max(1, SS // 3))
    d.line([(0, 0), (w, 0)], fill=(64, 64, 70), width=SS)
    for x0 in (2 * SS, w - 5 * SS): d.rectangle([x0, mid - 4 * SS, x0 + 3 * SS, mid + 4 * SS], fill=(92, 92, 98))   # (hinge pins)
    return rounded(im, 6 * SS).resize((CW, CH), Image.LANCZOS)


CARD_STYLES = {"parchment": card, "black": card_black, "wood": card_wood, "board": card_board}   # (scene.json "card_style")


def banner(text):
    size = 64; f = ImageFont.truetype(LINING, size * SS); pad = 24 * SS
    w = int(f.getlength(text)) + 2 * pad; h = int(size * 1.4) * SS + 2 * pad
    m = Image.new("L", (w, h)); ImageDraw.Draw(m).text((pad, pad + size * SS), text, font=f, fill=255, anchor="ls")
    return card_extras.glowing(m.resize((w // SS, h // SS), Image.LANCZOS), 6, 1.6, 0.7)


def cards_blob(greeting, style="parchment"):
    blob = bytearray(b"VFC1") + struct.pack("<HHB", CW, CH, 10)
    PAD = 18
    sh = Image.new("L", (CW + 2 * PAD, CH + 2 * PAD), 0)
    ImageDraw.Draw(sh).rounded_rectangle([PAD, PAD + 6, PAD + CW - 1, PAD + CH + 5], radius=14, fill=160)
    sh = sh.filter(ImageFilter.GaussianBlur(7))
    shadow = Image.merge("RGBA", (*Image.new("RGB", sh.size, (0, 4, 14)).split(), sh))
    blob += struct.pack("<hhHH", -PAD, -PAD, shadow.width, shadow.height) + premultiplied(shadow)
    draw = CARD_STYLES.get(style, card)
    for k in range(10):
        c = draw(k)
        blob += premultiplied(c.crop((0, 0, CW, CH // 2))) + premultiplied(c.crop((0, CH // 2, CW, CH)))
    for _ in ("DAYS", "DAY"):                                 # (the format has them; not shown: label_gap -1)
        blob += struct.pack("<HH", 1, 1) + premultiplied(Image.new("RGBA", (1, 1)))
    for img in (banner(greeting), card_extras.colon(CH)):
        blob += struct.pack("<HH", img.width, img.height) + premultiplied(img)
    return bytes(blob)


def water_into(work, out_dir):
    """The scene's own water (work/water.png, white where there's water) as water.raw.gz: how much each
    pixel ripples, fading to nothing over a few pixels at the shore. True if there is some; else any
    old water.raw.gz is gone."""
    wp, dst = os.path.join(work, "water.png"), os.path.join(out_dir, "water.raw.gz")
    m = Image.open(wp).convert("L").resize((W, H)).point(lambda v: 255 if v > 127 else 0) if os.path.exists(wp) else None
    if m is None or not m.getbbox():
        if os.path.exists(dst): os.remove(dst)
        return False
    soft = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(2.5))
    soft = ImageChops.multiply(soft, m)                                  # (none outside the water)
    Out(out_dir).gz("water.raw.gz", soft.tobytes())
    return True


def twinkle_blob(pts, orb):
    """twinkle.bin.gz's contents: "VTW2", the count, the sphere's circle, then each light's x, y and its
    place on the sphere as the camera sees it: how far round (0..65535 the whole way; the side facing the
    camera is the middle half), how high (-16384..16384, pole to pole), how far from the picture's middle
    (0..1024): what the show's patterns run over (the drawing library has no trigonometry of its own)."""
    import math
    cx, cy, r = (float(orb["cx"]), float(orb["cy"]), float(orb["r"])) if orb else (W / 2, H / 2, float(W))
    out = bytearray(b"VTW2" + struct.pack("<IHHHH", len(pts), int(cx), int(cy), max(1, int(r)), 0))
    for x, y in pts:
        nx, ny = (x - cx) / r, (y - cy) / r
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        lon = (math.atan2(nx, nz) / (2 * math.pi) + 0.5) % 1.0          # (0.25..0.75 facing the camera)
        lat = math.asin(max(-1.0, min(1.0, -ny)))
        d = min(1.0, math.hypot(nx, ny))
        out += struct.pack("<HHHhH", int(x), int(y), int(lon * 65535), int(lat / (math.pi / 2) * 16384), int(d * 1024))
    return bytes(out)


SHOW = ["waves", "rings", "blink", "spin", "rise", "wash", "sparkle", "spiral", "comet", "heartbeat"]   # (the library's TW_*, in order)


LIGHTS = 500


def orb_lights(orb, mask_path):
    """Light positions over a sphere's visible half, as the camera sees it: rings of latitude, each with
    as many lights as fit at `spacing` (so they crowd toward the rim, as on a real sphere), in screen
    pixels; only where the mask (if any) is white."""
    import math
    cx, cy, r = float(orb["cx"]), float(orb["cy"]), float(orb["r"])
    # (no spacing given: about LIGHTS of them, whatever the orb's size: each is drawn every frame on the board)
    sp = float(orb["spacing"]) if orb.get("spacing") else max(6.0, r * math.sqrt(1.74 * math.pi / LIGHTS))
    mask = None
    if os.path.exists(mask_path): mask = Image.open(mask_path).convert("L").resize((W, H), Image.LANCZOS).load()
    pts, seen = [], set()
    rings = max(3, int(math.pi * r / sp))                     # (along a meridian, the front's half-circumference)
    for i in range(1, rings):
        lat = -math.pi / 2 + math.pi * i / rings             # (the poles: none)
        ring_r = r * math.cos(lat)
        n = max(1, int(2 * math.pi * ring_r / sp))
        for j in range(n):
            lon = 2 * math.pi * (j + 0.5 * (i % 2)) / n      # (alternate rings offset: the panels' triangles)
            z = math.cos(lat) * math.cos(lon)
            if z < 0.12: continue                            # (the far side, and the very rim)
            x, y = round(cx + ring_r * math.sin(lon)), round(cy - r * math.sin(lat))
            if not (0 <= x < W and 0 <= y < H) or (x, y) in seen: continue
            if mask and mask[x, y] < 128: continue
            seen.add((x, y)); pts.append((x, y))
    return pts


def pack(work, out_dir, greeting=None, horizon=None, stars=True):
    conf = {}
    try: conf = json.load(open(os.path.join(work, "scene.json")))
    except (OSError, ValueError): pass
    greeting = greeting or conf.get("greeting") or "Have a magical day!"
    horizon = int(round(horizon if horizon is not None else conf.get("horizon", H - 60)))
    out = Out(out_dir)
    plates = {k: Image.open(os.path.join(work, k + ".png")).convert("RGB").resize((W, H), Image.LANCZOS) for k in ("day", "dusk", "night")}
    mp = os.path.join(work, "mask.png")
    if os.path.exists(mp):
        m = Image.open(mp)
        m = m.getchannel("A") if m.mode in ("RGBA", "LA") else m.convert("L")
        notsky = m.resize((W, H), Image.LANCZOS).point(lambda v: 255 if v > 100 else 0)
    else: notsky = Image.new("L", (W, H), 0)
    # (everything below the horizon too; not for a ship's scene: its mask is the ship's outline, the sea round
    # it ripples, and the wake and the bow wave know where the hull is: scene.json "mask_as_is")
    if not conf.get("mask_as_is"): notsky.paste(255, (0, horizon, W, H))
    out.gz("mask.raw.gz", notsky.tobytes())
    if stars and conf.get("stars", True): plates["night"] = add_stars(plates["night"], notsky, horizon)
    for k, im in plates.items(): out.gz(k + ".rgb.gz", im.tobytes())
    out.gz("settings_bg.rgb.gz", plates["day"].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)).tobytes())
    wp = os.path.join(work, "windows.png")
    if os.path.exists(wp): blob, light, n = window_lights(Image.open(wp), tuple(conf.get("light", (255, 168, 80))), not conf.get("windows_painted"),
                                                          frame_picture(work), window_groups(work))
    elif conf.get("lights_fixed") and os.path.exists(os.path.join(work, conf["lights_fixed"])):
        # (window light made elsewhere, as it was: the cruise's cabins, until its windows are edited here)
        blob = gzip.open(os.path.join(work, conf["lights_fixed"])).read(); light, n = lights_picture(blob)
    else: blob, light, n = b"VLT1" + struct.pack("<II", 0, 1), Image.new("RGB", (W, H)), 0
    out.gz("lights.bin.gz", blob)
    out.gz("cards.bin.gz", cards_blob(greeting, conf.get("card_style", "parchment")))
    effects = list(conf.get("effects", []))
    if water_into(work, out_dir) and "water" not in effects: effects.append("water")   # (a scene's own water: the ripple)
    tw = os.path.join(out_dir, "twinkle.bin.gz")
    tp = os.path.join(work, "twinkle_points.json")                       # (the lights' places, found in the photo)
    if conf.get("orb"):
        pts = [tuple(p) for p in json.load(open(tp))] if os.path.exists(tp) else orb_lights(conf["orb"], os.path.join(work, "twinkle_mask.png"))
        out.gz("twinkle.bin.gz", twinkle_blob(pts, conf["orb"]))
        if "twinkle" not in effects: effects.append("twinkle")
        print("twinkle: %d lights on the orb" % len(pts))
    elif os.path.exists(tw): os.remove(tw)
    theme = {"effects": effects, "horizon": horizon, "fireworks_scale": conf.get("fireworks_scale", 0.85), "cards": dict(CARDS, **conf.get("cards", {}))}
    if conf.get("smoke", {}).get("points"):                              # (smoke from points: a campfire, a chimney)
        if "smoke" not in effects: effects.append("smoke")
        theme["smoke"] = conf["smoke"]
    if conf.get("birds") and "birds" not in effects: effects.append("birds")
    if conf.get("foam", {}).get("points"):                               # (white water: a waterfall's foot, rapids, surf)
        if "foam" not in effects: effects.append("foam")
        theme["foam"] = conf["foam"]
    if "water" in effects: theme["water"] = {"strength": conf.get("water", {}).get("strength", 1.0), "speed": conf.get("water", {}).get("speed", 1.0)}
    # (a scene's own extra settings, as they are: a ship's funnels, bow, stern, mast, tube... scene.json "theme_extra")
    for k, v in (conf.get("theme_extra") or {}).items(): theme.setdefault(k, v)
    if conf.get("show"):                                                  # (the lights' show: its patterns, in turn)
        bad = [n for n in conf["show"].get("program", []) if n not in SHOW]
        if bad: sys.exit("scene_pack: no light pattern %s (there are: %s)" % (", ".join(bad), ", ".join(SHOW)))
        theme["show"] = {"program": [SHOW.index(n) for n in conf["show"].get("program", [])], "secs": conf["show"].get("secs", 12)}
    json.dump(theme, open(os.path.join(out_dir, "theme.json"), "w"), indent=1)
    sheet = Image.new("RGB", (W * 3 + 32, H + 16), (18, 20, 24))
    for k, im in enumerate((plates["day"], plates["dusk"], ImageChops.add(plates["night"], light))): sheet.paste(im, (8 + k * (W + 8), 8))
    sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS).save(os.path.join(out_dir, "preview.png"))
    print("scene: %s (%d windows, horizon %d, \"%s\")" % (os.path.relpath(out_dir, REPO), n, horizon, greeting))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work"); ap.add_argument("out")
    ap.add_argument("--greeting"); ap.add_argument("--horizon", type=float)
    ap.add_argument("--no-stars", action="store_true")
    a = ap.parse_args()
    pack(a.work, a.out, a.greeting, a.horizon, not a.no_stars)


if __name__ == "__main__":
    main()
