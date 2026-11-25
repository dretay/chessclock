#!/usr/bin/env python3
"""A countdown app's scene from one daytime photo: day, dusk and night, the sky mask, packed into the
app (scene_pack.py). Pillow only.

    python3 tools/themegen/photo_scene.py PHOTO APP --try [--orb auto|CX,CY,R] [--crop X,Y,W,H] [--keep-mask] [--no-preview]
    python3 tools/themegen/photo_scene.py --list APP          the photos tried, * the one shown
    python3 tools/themegen/photo_scene.py --keep NAME APP     that one into the app
    python3 tools/themegen/photo_scene.py --back APP          the previewer back to the app's own scene
    python3 tools/themegen/photo_scene.py PHOTO APP           straight into the app, no trial

e.g.  python3 tools/themegen/photo_scene.py ~/Pictures/spaceship-earth.jpg epcot --try --orb auto

Trying: each photo becomes a trial scene in build/trial/APP/<photo's name>/ (its pictures in work/,
the packed scene in scene/, with a day/dusk/night sheet, preview.png), and the previewer opens on it
(or, open already, switches to it within a second): its Controls panel slides the time of day and
sets off fireworks. The app itself is untouched until --keep. Run --try again on the same photo with --orb, --crop or a painted mask to
adjust it: its work/scene.json keeps what's set.

- the photo is cut to the screen's shape (5:3; --crop picks the part, in the photo's pixels; else the
  middle) and scaled to 800x480: day.png
- with --orb (the sphere's circle on the screen): its night lights, only where its own surface shows
  (twinkle_mask.png: a guess from the panels' pattern; paint it and use --keep-mask to keep it)
- the sky is found (blue-tinted, joined to the top edge, without big jumps in colour): mask.png, white
  where it isn't sky; the "orb" in scene.json, if there is one, is never sky (a pale, sky-reflecting
  sphere fools any guess). If it's wrong somewhere, paint mask.png (white = not sky) and run again
  with --keep-mask
- dusk.png and night.png: the photo darkened and cooled, its sky replaced by a sunset, then a night sky
- all into tools/themegen/work/APP/ (beside its scene.json: the horizon, set from the sky the first
  time, the greeting, the card layout, an "orb" for the twinkle lights; edit it and run again), then
  packed into apps/APP/scenes/<its scene>/. With the previewer open on the app, it restarts with them.
"""
import argparse, gzip, json, os, shutil, struct, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); import scene_pack
W, H = 800, 480


def cut(photo, crop):
    """The photo cut to 5:3 (crop: x, y, w, h; else the largest 5:3 in its middle), at 800x480."""
    return photo.crop(crop_box(photo, crop)).resize((W, H), Image.LANCZOS)


def find_sky(day):
    """255 where it isn't sky: blue-tinted and joined to the top edge, and whatever floats free of the ground (at a quarter size,
    so clouds' edges don't break it up), smoothed."""
    sw, sh = W // 4, H // 4
    small = day.resize((sw, sh), Image.BOX).filter(ImageFilter.MedianFilter(3)); px = small.load()
    def skyish(c):
        r, g, b = c
        return b > 90 and b >= r + 10 and b + 6 >= g                    # blue-tinted (clouds in daylight too)
    sky = [[False] * sw for _ in range(sh)]
    stack = [(x, 0) for x in range(sw) if skyish(px[x, 0])]
    for x, y in stack: sky[y][x] = True
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < sw and 0 <= ny < sh and not sky[ny][nx]:
                a, b = px[x, y], px[nx, ny]
                if skyish(b) and sum(abs(p - q) for p, q in zip(a, b)) < 36: sky[ny][nx] = True; stack.append((nx, ny))
    # what's left and stands on the ground (joined to the bottom edge) is the subject; what floats (white
    # clouds, too neutral to pass for sky) is sky too
    ground = [[False] * sw for _ in range(sh)]
    stack = [(x, sh - 1) for x in range(sw) if not sky[sh - 1][x]]
    for x, y in stack: ground[y][x] = True
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < sw and 0 <= ny < sh and not sky[ny][nx] and not ground[ny][nx]: ground[ny][nx] = True; stack.append((nx, ny))
    for y in range(sh):
        for x in range(sw):
            if not ground[y][x]: sky[y][x] = True
    m = Image.new("L", (sw, sh), 255); mp = m.load()
    for y in range(sh):
        for x in range(sw):
            if sky[y][x]: mp[x, y] = 0
    m = m.resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 255 if v > 127 else 0)
    # the edge, at full size: next to the sky, what's still blue-tinted and smooth (no edges, no pattern) is
    # sky too (the paler sky beside a bright edge stops the quarter-size fill a few pixels short of it)
    g = day.convert("L")
    smooth_ = ImageChops.difference(g, g.filter(ImageFilter.GaussianBlur(2))).filter(ImageFilter.BoxBlur(2)).load()
    dp = day.load()
    for _ in range(3):
        near = m.filter(ImageFilter.MinFilter(9)).load(); mp = m.load(); changed = 0
        for y in range(H):
            for x in range(W):
                if mp[x, y] and not near[x, y]:                          # (not sky, within 4 px of sky)
                    r, gg, b = dp[x, y]
                    if b >= r + 6 and b + 10 >= gg and smooth_[x, y] < 5: mp[x, y] = 0; changed += 1
        if not changed: break
    return m


def orb_surface(day, orb):
    """Where the sphere's own surface shows inside its circle (white): grey and busy with its panels'
    pattern; not what's in front of it (smooth white supports, green trees, a sculpture). A first guess,
    to paint over (twinkle_mask.png)."""
    cx, cy, r = orb
    grey = day.convert("L")
    # local detail: the difference from a blurred copy, averaged around each pixel
    detail = ImageChops.difference(grey, grey.filter(ImageFilter.GaussianBlur(3))).filter(ImageFilter.BoxBlur(5))
    px, dp = day.load(), detail.load()
    m = Image.new("L", (W, H), 0); mp = m.load()
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        for x in range(max(0, cx - r), min(W, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 > r * r: continue
            rr, gg, bb = px[x, y]
            grey_or_sky = max(rr, gg, bb) - min(rr, gg, bb) < 48 or (bb >= rr and bb >= gg and rr + gg + bb > 360)   # (panels reflect the sky)
            if grey_or_sky and dp[x, y] > 9: mp[x, y] = 255
    # fill the pattern's gaps, then drop specks (a few stray textured bits on the trees)
    m = m.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MaxFilter(3))
    return m


def find_orb(day, horizon=H):
    """(cx, cy, r) of the photo's sphere, in screen pixels, or None: where its panels' look is (grey or
    sky-tinted, and busy) above the horizon (not the ground's grey), worn away until what touches it (trees, supports, the ground) comes apart,
    the largest piece left; the circle across its widest rows (its equator: the bottom may be hidden by
    what's in front), grown back by what was worn away."""
    sw, sh, ERODE = W // 4, H // 4, 9                          # (a quarter size; worn away 4 cells each side)
    small = day.resize((sw, sh), Image.BOX)
    grey = small.convert("L")
    detail = ImageChops.difference(grey, grey.filter(ImageFilter.GaussianBlur(1.5))).filter(ImageFilter.BoxBlur(2))
    px, dp = small.load(), detail.load()
    m = Image.new("L", (sw, sh), 0); mp = m.load()
    for y in range(sh):
        for x in range(sw):
            r, g, b = px[x, y]
            if y * 4 < horizon and (max(r, g, b) - min(r, g, b) < 48 or (b >= r and b >= g and r + g + b > 360)) and dp[x, y] > 6: mp[x, y] = 255
    m = m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))       # (close the pattern's gaps)
    core = m.filter(ImageFilter.MinFilter(ERODE)); cp = core.load()
    seen, best = set(), []
    for y0 in range(sh):
        for x0 in range(sw):
            if cp[x0, y0] < 128 or (x0, y0) in seen: continue
            stack, part = [(x0, y0)], []; seen.add((x0, y0))
            while stack:
                x, y = stack.pop(); part.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < sw and 0 <= ny < sh and cp[nx, ny] >= 128 and (nx, ny) not in seen: seen.add((nx, ny)); stack.append((nx, ny))
            if len(part) > len(best): best = part
    if len(best) < 60: return None
    # its outline (not where it meets the picture's edge), and the circle that fits it best: fitted again
    # without the points furthest off (a tree or a support bulging out of it) until they agree
    inside = set(best)
    edge = [(x, y) for x, y in best if 0 < x < sw - 1 and 0 < y < sh - 1
            and any((x + dx, y + dy) not in inside for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    pts = edge
    for _ in range(8):
        c = fit_circle(pts)
        if not c: return None
        cx, cy, r = c
        res = sorted((abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - r), x, y) for x, y in pts)
        keep = [(x, y) for d, x, y in res[:max(12, int(len(res) * 0.8))] if d < 2.5 or len(res) < 12]
        if len(keep) == len(pts): break
        pts = keep
    cx, cy, r = fit_circle(pts)
    r += ERODE // 2                                          # (what was worn away)
    return round(cx * 4 + 2), round(cy * 4 + 2), round(r * 4)


def refine_orb(notsky, orb):
    """The sphere's circle fitted to its outline against the sky: the outline's points near the first
    guess, and the circle the most of them lie on (circles through three of them at random, a few
    thousand times: a tree's or a pylon's edge beside it isn't round, so it can't win), then least
    squares on those. The first guess back if there's too little outline."""
    import math, random
    cx, cy, r = orb; mp = notsky.load()
    rim = [(x, y) for y in range(1, H - 1) for x in range(1, W - 1)
           if mp[x, y] > 127 and any(mp[x + dx, y + dy] < 128 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
           and abs(math.hypot(x - cx, y - cy) - r) < 40]
    if len(rim) < 30: return orb
    rnd = random.Random(1); best, bc = 0, None
    for _ in range(3000):
        c = fit_circle(rnd.sample(rim, 3))
        if not c or not (0.6 * r < c[2] < 1.4 * r): continue
        n = sum(1 for x, y in rim if abs(math.hypot(x - c[0], y - c[1]) - c[2]) < 2.0)
        if n > best: best, bc = n, c
    if not bc or best < 30: return orb
    fit = fit_circle([(x, y) for x, y in rim if abs(math.hypot(x - bc[0], y - bc[1]) - bc[2]) < 2.5]) or bc
    return round(fit[0]), round(fit[1]), round(fit[2])


def fit_circle(pts):
    """The circle (cx, cy, r) through points, least squares (x^2 + y^2 + D x + E y + F = 0); None if they're a line."""
    n = len(pts)
    if n < 3: return None
    sx = sum(x for x, _ in pts); sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts); syy = sum(y * y for _, y in pts); sxy = sum(x * y for x, y in pts)
    sz = [-(x * x + y * y) for x, y in pts]
    b = [sum(z * x for z, (x, _) in zip(sz, pts)), sum(z * y for z, (_, y) in zip(sz, pts)), sum(sz)]
    a = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
    def det(m): return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det(a)
    if abs(d) < 1e-9: return None
    sol = []
    for k in range(3):                                       # (Cramer's rule)
        m = [row[:] for row in a]
        for i in range(3): m[i][k] = b[i]
        sol.append(det(m) / d)
    D, E, F = sol
    cx, cy = -D / 2, -E / 2
    rr = cx * cx + cy * cy - F
    return (cx, cy, rr ** 0.5) if rr > 0 else None


def orb_troughs(photo, crop, mask, orb):
    """The sphere's troughs, where its panels' corners meet (six faces round a recessed, darker point),
    found in the full-size photo (at the screen's size they're a pixel or two), as screen points: where
    its lights go. Each candidate: on a small ring round it, light and dark at least six times, and its
    middle darker than the ring; the strongest kept, no two closer than the panels' spacing (from the
    orb's size: about a fifteenth of its radius). Toward the rim the surface turns away, so the panels
    look squashed along the radius: the ring and the spacing are squashed the same way there. Only where
    mask (screen size) is white."""
    import math
    big = photo.crop(crop_box(photo, crop)); k = big.width / W             # (photo pixels per screen pixel)
    g = big.convert("L").filter(ImageFilter.GaussianBlur(max(0.6, k / 3))); gp = g.load()
    bmask = mask.resize(big.size); mp = bmask.load()
    cx, cy, r = orb[0] * k, orb[1] * k, orb[2] * k
    ring, N, s0 = 0.018 * r, 16, 0.068 * r
    DIRS, TILTS = 32, 8                                                   # (rings worked out once for each)
    rings = {}
    for di in range(DIRS):
        a0 = 2 * math.pi * di / DIRS; ux, uy = math.cos(a0), math.sin(a0)
        for ti in range(TILTS):
            cosv = 0.3 + 0.7 * (ti + 0.5) / TILTS
            rings[di, ti] = [(round(ring * math.cos(2 * math.pi * i / N) * cosv * ux - ring * math.sin(2 * math.pi * i / N) * uy),
                              round(ring * math.cos(2 * math.pi * i / N) * cosv * uy + ring * math.sin(2 * math.pi * i / N) * ux)) for i in range(N)]
    def tilt(x, y):
        dx, dy = x - cx, y - cy; d = math.hypot(dx, dy)
        cosv = math.sqrt(max(0.09, 1 - min(1.0, d / r) ** 2))
        di = int(round(math.atan2(dy, dx) / (2 * math.pi) * DIRS)) % DIRS
        return cosv, di, (dx / d, dy / d) if d > 1 else (1.0, 0.0)
    R = int(ring) + 2; step = max(1, int(k * 0.6))
    bb = bmask.getbbox() or (0, 0, big.width, big.height)
    cand = []
    for y in range(max(R, bb[1]), min(big.height - R, bb[3]), step):
        for x in range(max(R, bb[0]), min(big.width - R, bb[2]), step):
            if mp[x, y] < 128: continue
            cosv, di, u = tilt(x, y)
            ti = min(TILTS - 1, max(0, int((cosv - 0.3) / 0.7 * TILTS)))
            s = [gp[x + dx, y + dy] for dx, dy in rings[di, ti]]
            mean = sum(s) / N
            if gp[x, y] > mean - 6: continue                             # (a trough is recessed; a pyramid's peak isn't)
            cross = sum(1 for i in range(N) if (s[i] - mean) * (s[i - 1] - mean) < 0)
            if cross < 6: continue                                       # (six faces round it, not a face's corner)
            sd = (sum((v - mean) ** 2 for v in s) / N) ** 0.5
            cand.append((-(sd * cross / 6 + (mean - gp[x, y]) * 0.5), x, y, cosv, u))
    cand.sort()
    cell = max(1, int(s0)); grid = {}; pts = []                           # (a grid, so the spacing test stays quick)
    for _, x, y, cosv, (ux, uy) in cand:
        gx, gy = x // cell, y // cell; near = False
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for a, b in grid.get((gx + i, gy + j), ()):
                    dx, dy = x - a, y - b
                    rad, tan = dx * ux + dy * uy, -dx * uy + dy * ux      # (closer along the radius where it's tilted)
                    if (rad / cosv) ** 2 + tan ** 2 < s0 * s0: near = True; break
                if near: break
            if near: break
        if near: continue
        grid.setdefault((gx, gy), []).append((x, y)); pts.append((round(x / k), round(y / k)))
    return pts


def edited(pts, work):
    """The lights after the edits made in the previewer, in order (work/edits.json: [{"erase": [[x, y, r],
    ...]} or {"add": [[x, y], ...]}, ...]): a rub-out takes the lights under it (added ones too), an
    addition puts lights in. (work/erase.json, from before additions: rub-outs only.)"""
    try: edits = json.load(open(os.path.join(work, "edits.json")))
    except (OSError, ValueError):
        try: edits = [{"erase": json.load(open(os.path.join(work, "erase.json")))}]
        except (OSError, ValueError): edits = []
    pts = list(pts)
    for e in edits:
        for a, b, r in e.get("erase", []): pts = [(x, y) for x, y in pts if (x - a) ** 2 + (y - b) ** 2 > r * r]
        for x, y in e.get("add", []):
            if all((x - a) ** 2 + (y - b) ** 2 > 9 for a, b in pts): pts.append((int(x), int(y)))
    return pts


def relight(work, scene):
    """After an edit in the previewer: the lights again from what was found, then every edit, into
    work/twinkle_points.json and the scene's twinkle.bin.gz (nothing else rebuilt: quick). The count."""
    try: found = [tuple(p) for p in json.load(open(os.path.join(work, "twinkle_found.json")))]
    except (OSError, ValueError): return None
    try: orb = json.load(open(os.path.join(work, "scene.json"))).get("orb")
    except (OSError, ValueError): orb = None
    pts = edited(found, work)
    json.dump(pts, open(os.path.join(work, "twinkle_points.json"), "w"))
    scene_pack.Out(scene).gz("twinkle.bin.gz", scene_pack.twinkle_blob(pts, orb))
    return len(pts)


def lights_on_orb(notsky, pts, orb):
    """The lights left once the plainly wrong ones are out: outside the sphere's circle (a tree or a
    pylon beside it), and in the sky or right beside it (5 px). (Not by colour: in low sun its panels
    are as golden as the leaves.) What's in front of the sphere, inside its circle (a glass sculpture
    reflecting it, a tree's branches), can't be told apart: rub it out in the previewer (Erase lights)."""
    cx, cy, r = orb
    inside = notsky.filter(ImageFilter.MinFilter(11)).load()
    return [(x, y) for x, y in pts if 0 <= x < W and 0 <= y < H and inside[x, y] >= 128
            and (x - cx) ** 2 + (y - cy) ** 2 <= (r - 3) ** 2]


def crop_box(photo, crop):
    """The part of the photo cut to the screen (x0, y0, x1, y1): crop, else the largest 5:3 in its middle."""
    if crop: x, y, w, h = crop; return (x, y, x + w, y + h)
    w = min(photo.width, photo.height * W // H); h = w * H // W
    x, y = (photo.width - w) // 2, (photo.height - h) // 2
    return (x, y, x + w, y + h)


def edge_to_sky(day, notsky):
    """The subject's outline cleaned: within 4 px of the sky, what's plainly sky-blue (much bluer than
    red: no panel, stone or leaf is) is sky, so no rim of the day's sky stays on the subject (at night it
    would show as a pale halo)."""
    m = notsky.copy(); dp = day.load()
    for _ in range(3):
        near = m.filter(ImageFilter.MinFilter(9)).load(); mp = m.load(); changed = 0
        for y in range(H):
            for x in range(W):
                if mp[x, y] and not near[x, y]:
                    r, g, b = dp[x, y]
                    if b - r > 55 and b + 10 >= g: mp[x, y] = 0; changed += 1
        if not changed: break
    return m


def lerp(a, b, t): return a + (b - a) * t


def sky_gradient(stops, horizon):
    """A sky: colours from the top to the horizon (stops: [(0..1, (r, g, b))]), the last one below it."""
    im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):
        t = min(1.0, y / max(1, horizon))
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t <= t1:
                k = (t - t0) / max(1e-6, t1 - t0); c = tuple(int(lerp(a, b, k)) for a, b in zip(c0, c1)); break
        d.line([(0, y), (W, y)], fill=c)
    return im


def grade(day, n, d, horizon):
    """The photo at night (n = 1) or dusk (d = 1): desaturated, each channel scaled, a warm or cool tint
    rising from the horizon (the cruise's grade)."""
    out = Image.blend(day, day.convert("L").convert("RGB"), 0.45 * n + 0.15 * d)
    mr, mg, mb = lerp(1, 0.16, n) * lerp(1, 0.92, d), lerp(1, 0.2, n) * lerp(1, 0.66, d), lerp(1, 0.34, n) * lerp(1, 0.58, d)
    r, g, b = out.split()
    out = Image.merge("RGB", (r.point(lambda v: min(255, int(v * mr + 0.5))), g.point(lambda v: min(255, int(v * mg + 0.5))),
                              b.point(lambda v: min(255, int(v * mb + 0.5)))))
    tint = Image.new("RGB", (W, H)); td = ImageDraw.Draw(tint)
    for y in range(H):
        if y <= horizon: k = (y / max(1, horizon)) ** 2.2; c = (d * 70 * k + n * 2, d * 26 * k + n * 5, d * 6 * k + n * 14)
        else: k = (1 - (y - horizon) / max(1, H - horizon)) ** 6; c = (d * 40 * k, d * 14 * k, 0)
        td.line([(0, y), (W, y)], fill=tuple(int(v + 0.5) for v in c))
    return ImageChops.add(out, tint)


DUSK_SKY = [(0.0, (38, 42, 96)), (0.45, (128, 82, 128)), (0.8, (236, 132, 92)), (1.0, (252, 190, 120))]
NIGHT_SKY = [(0.0, (4, 7, 20)), (0.7, (14, 22, 50)), (1.0, (30, 40, 76))]


def trial_root(app): return os.path.join(REPO, "build", "trial", app)


def set_current(app, name):
    """Which trial the previewer shows ("" for the app's own scene): build/trial/APP/current."""
    os.makedirs(trial_root(app), exist_ok=True)
    with open(os.path.join(trial_root(app), "current"), "w") as f: f.write(name + "\n")   # (written either way: its time restarts the preview)


def make(photo, work, out, crop, orb, keep_mask, base_conf=None):
    """The photo into work/ (day, dusk, night, mask, scene.json), packed into out/."""
    os.makedirs(work, exist_ok=True)
    # a scene whose plates and mask were made by hand (scene.json "plates_fixed": the cruise's, lowered, its
    # bow wave painted out, its own grade and outline): made again, they stay as they are
    try: fixed = json.load(open(os.path.join(work, "scene.json"))).get("plates_fixed")
    except (OSError, ValueError): fixed = False
    if fixed: keep_mask = True
    full = Image.open(os.path.expanduser(photo)).convert("RGB")
    day = cut(full, crop)
    mp = os.path.join(work, "mask.png")
    if keep_mask and os.path.exists(mp): notsky = Image.open(mp).convert("L").resize((W, H)).point(lambda v: 255 if v > 127 else 0)
    else:
        day.save(os.path.join(work, "day.png"))                           # (the model looks at it)
        seg = segmentation(work)
        notsky = kinds_mask(seg, ("sky",)).point(lambda v: 0 if v else 255) if seg else find_sky(day)
        notsky.save(mp)
    sp = os.path.join(work, "scene.json")
    try: conf = json.load(open(sp))
    except (OSError, ValueError): conf = dict(base_conf or {})
    if orb and orb != "auto": conf["orb"] = dict(conf.get("orb") or {}, cx=orb[0], cy=orb[1], r=orb[2])
    conf["photo"] = os.path.abspath(os.path.expanduser(photo))
    if crop: conf["crop"] = list(crop)
    if "horizon" not in conf:                                          # (the first time: where the sky ends, in most columns)
        bottoms = sorted(max((y for y in range(H) if not notsky.getpixel((x, y))), default=0) for x in range(0, W, 8))
        conf["horizon"] = min(H - 40, max(120, bottoms[len(bottoms) * 3 // 4] + 6))
    auto = orb == "auto"
    if orb == "auto":
        orb = find_orb(day, conf["horizon"])
        if orb: print("orb: found at %d,%d, radius %d (if that's off: --orb CX,CY,R)" % orb); conf["orb"] = dict(conf.get("orb") or {}, cx=orb[0], cy=orb[1], r=orb[2])
        else: print("orb: no sphere found in the photo (give it: --orb CX,CY,R, in screen pixels of 800x480)")
    json.dump(conf, open(sp, "w"), indent=1)
    hz = conf["horizon"]
    tp = os.path.join(work, "twinkle_points.json")
    if conf.get("orb"):
        o = conf["orb"]
        tm = os.path.join(work, "twinkle_mask.png")                     # (where its lights show: a guess, unless painted)
        if not (keep_mask and os.path.exists(tm)): orb_surface(day, (o["cx"], o["cy"], o["r"])).save(tm)
        surface = Image.open(tm).convert("L")
        # the sphere's own surface is never sky, whatever its colour (pale, reflecting it): its panels, their
        # gaps closed; not the whole circle (a circle a little off would keep a crescent of the day's sky)
        notsky = ImageChops.lighter(notsky, surface.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(7)))
    if not keep_mask: notsky = edge_to_sky(day, notsky); notsky.save(mp)   # (a painted mask is left as painted)
    if conf.get("orb"):
        if auto:                                                          # (found: fitted to its outline against the final sky)
            fit = refine_orb(notsky, (o["cx"], o["cy"], o["r"]))
            if fit != (o["cx"], o["cy"], o["r"]):
                print("orb: fitted to its outline: %d,%d, radius %d" % fit)
                o = conf["orb"] = dict(o, cx=fit[0], cy=fit[1], r=fit[2]); json.dump(conf, open(sp, "w"), indent=1)
        pts = orb_troughs(full, crop, surface, (o["cx"], o["cy"], o["r"]))   # (its lights: on the panels' troughs)
        pts = lights_on_orb(notsky, pts, (o["cx"], o["cy"], o["r"]))
        json.dump(pts, open(os.path.join(work, "twinkle_found.json"), "w"))   # (before the strokes rubbed out by hand)
        pts = edited(pts, work)
        json.dump(pts, open(tp, "w"))
        print("orb: %d troughs for its lights" % len(pts))
    elif os.path.exists(tp): os.remove(tp)
    sky = notsky.point(lambda v: 255 - v).filter(ImageFilter.GaussianBlur(1.5))       # (soft edge onto the subject)
    if not fixed:
        dusk = Image.composite(sky_gradient(DUSK_SKY, hz), grade(day, 0, 1, hz), sky)
        night = Image.composite(sky_gradient(NIGHT_SKY, hz), grade(day, 1, 0, hz), sky)
        day.save(os.path.join(work, "day.png")); dusk.save(os.path.join(work, "dusk.png")); night.save(os.path.join(work, "night.png"))
    print("photo: %s (horizon %d%s)" % (photo, hz, ", orb at %d,%d r %d" % (conf["orb"]["cx"], conf["orb"]["cy"], conf["orb"]["r"]) if conf.get("orb") else ""))
    scene_pack.pack(work, out)


def open_preview(app):
    """The previewer on this app: started (in the background, its window) if it isn't running; else asked
    to switch to the app (it restarts it with the trial either way)."""
    import fcntl, subprocess
    state = os.path.join(REPO, "build", "preview")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "lock"), "a+") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); running = False; fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError: running = True
    if running:
        with open(os.path.join(state, "switch-request"), "w") as f: f.write(app + "\n")
        print("preview: showing it in the open previewer"); return
    log = open(os.path.join(state, "preview.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(REPO, "tools", "preview", "preview.py"), app], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=REPO)
    print("preview: opening it (the App Preview window; Controls: the time of day, fireworks)")


# ---------------------------------------------------------------- what the previewer's Scene Builder calls
def app_dirs(app):
    """(the app's scene folder, its work folder) for an app made from a photo."""
    meta = json.load(open(os.path.join(REPO, "apps", app, "app.json")))
    return (os.path.join(REPO, "apps", app, meta["scene"]["dir"], meta["scene"]["default"]),
            os.environ.get("THEME_WORK") or os.path.join(HERE, "work", app))


def dirs(app, name):
    """(scene folder, work folder) of a trial, or ("" for name) the app's own scene."""
    if not name: return app_dirs(app)
    return os.path.join(trial_root(app), name, "scene"), os.path.join(trial_root(app), name, "work")


def trial_name(photo):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in os.path.splitext(os.path.basename(photo))[0])[:48].strip("-_") or "photo"


def try_photo(app, photo, orb=None, crop=None, keep_mask=False):
    """A photo as a trial scene for the app (its own copy of the photo kept with it), and the one shown.
    Its name."""
    name = trial_name(photo)
    d = os.path.join(trial_root(app), name); os.makedirs(d, exist_ok=True)
    own = os.path.join(d, "photo" + (os.path.splitext(photo)[1].lower() or ".jpg"))
    if os.path.abspath(os.path.expanduser(photo)) != os.path.abspath(own): shutil.copy(os.path.expanduser(photo), own)
    base = {}
    try: base = {k: v for k, v in json.load(open(os.path.join(app_dirs(app)[1], "scene.json"))).items() if k in ("greeting", "cards", "show")}
    except (OSError, ValueError): pass
    scene, work = dirs(app, name)
    make(own, work, scene, crop, orb, keep_mask, base)
    set_current(app, name)
    return name


def rebuild(app, name, orb=None, keep_mask=True):
    """A trial (or "": the app's own scene) made again from its photo: with an orb ("auto", (cx, cy, r)),
    without (False), or as it was (None); its painted masks and light edits kept."""
    scene, work = dirs(app, name)
    conf = json.load(open(os.path.join(work, "scene.json")))
    if orb is False:
        conf.pop("orb", None); json.dump(conf, open(os.path.join(work, "scene.json"), "w"), indent=1)
        for f in ("twinkle_found.json", "twinkle_points.json"):
            if os.path.exists(os.path.join(work, f)): os.remove(os.path.join(work, f))
        orb = None
    make(conf["photo"], work, scene, tuple(conf["crop"]) if conf.get("crop") else None, orb, keep_mask)


def trials(app):
    """The photos tried: [{"name", "current" (the one shown), "sheet" (day/dusk/night picture)}]."""
    root = trial_root(app)
    try: cur = open(os.path.join(root, "current")).read().strip()
    except OSError: cur = ""
    out = []
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if os.path.isdir(os.path.join(root, n, "scene")):
            out.append({"name": n, "current": n == cur, "sheet": os.path.join(root, n, "scene", "preview.png"),
                        "when": os.path.getmtime(os.path.join(root, n, "scene"))})
    return sorted(out, key=lambda t: -t["when"])


def keep_trial(app, name):
    """That trial into the app: its pictures, masks, settings and light edits into the app's work folder,
    packed into its scene; the previewer back to the app's own scene."""
    tw = os.path.join(trial_root(app), name, "work")
    if not os.path.isdir(tw): raise ValueError("no trial %s" % name)
    scene, work = app_dirs(app)
    os.makedirs(work, exist_ok=True)
    for f in PHOTO_FILES:
        src, dst = os.path.join(tw, f), os.path.join(work, f)
        if os.path.exists(src): shutil.copy(src, dst)
        elif os.path.exists(dst): os.remove(dst)
    for f in os.listdir(os.path.join(trial_root(app), name)):               # (its photo too, for making it again)
        if f.startswith("photo."): shutil.copy(os.path.join(trial_root(app), name, f), os.path.join(work, f))
    conf = json.load(open(os.path.join(work, "scene.json")))
    own = [f for f in os.listdir(work) if f.startswith("photo.")]
    if own: conf["photo"] = os.path.join(work, own[0]); json.dump(conf, open(os.path.join(work, "scene.json"), "w"), indent=1)
    scene_pack.pack(work, scene)
    set_current(app, "")


def delete_trial(app, name):
    d = os.path.join(trial_root(app), name)
    if name and os.path.isdir(d) and os.path.dirname(os.path.abspath(d)) == os.path.abspath(trial_root(app)): shutil.rmtree(d)
    try: cur = open(os.path.join(trial_root(app), "current")).read().strip()
    except OSError: cur = ""
    if cur == name: set_current(app, "")


def set_show(app, name, program, secs):
    """The lights' show for a trial (or the app's own scene): its patterns in turn, each secs long."""
    scene, work = dirs(app, name)
    sp = os.path.join(work, "scene.json"); conf = json.load(open(sp))
    conf["show"] = {"program": list(program), "secs": float(secs)}
    json.dump(conf, open(sp, "w"), indent=1)
    scene_pack.pack(work, scene)


def set_effect(app, name, key, value):
    """An effect's settings for a trial (or the app's own scene): "smoke" ({"points", "scale", "wind",
    "rate"}; no points: none), "foam" ({"points": [[x, y, r]], "amount", "flow"}) or "birds" (true or false). Into scene.json, and the scene's theme.json at
    once (no repack: the previewer restarts with it)."""
    scene, work = dirs(app, name)
    sp = os.path.join(work, "scene.json")
    if os.path.exists(sp):
        conf = json.load(open(sp)); conf[key] = value; json.dump(conf, open(sp, "w"), indent=1)
    tp = os.path.join(scene, "theme.json"); theme = json.load(open(tp))
    fx = [e for e in theme.get("effects", []) if e != key]
    if key in ("smoke", "foam"):
        if value and value.get("points"): fx.append(key); theme[key] = value
        else: theme.pop(key, None)
    elif key == "birds" and value: fx.append("birds")
    theme["effects"] = fx
    with open(tp + ".tmp", "w") as f: json.dump(theme, f, indent=1)
    os.replace(tp + ".tmp", tp)


def set_layout(app, name, cards=None, horizon=None, card_style=None):
    """Where the countdown's cards go ({"center_x", "top", "gap", "scale3"}) and the horizon, for a trial or
    the app's own scene. The cards: only theme.json changes (at once). The horizon: the scene packed again
    (below it is never sky: the mask changes). A scene not made from a photo (no work folder: the
    castle's, the cruise's): its theme.json alone, cards and horizon."""
    scene, work = dirs(app, name)
    sp = os.path.join(work, "scene.json")
    if os.path.exists(sp):
        conf = json.load(open(sp))
        if cards: conf["cards"] = dict(conf.get("cards") or {}, **{k: v for k, v in cards.items() if v is not None})
        if horizon is not None: conf["horizon"] = int(horizon)
        if card_style in scene_pack.CARD_STYLES: conf["card_style"] = card_style
        json.dump(conf, open(sp, "w"), indent=1)
        if horizon is not None: scene_pack.pack(work, scene); return
        if card_style in scene_pack.CARD_STYLES:                         # (the cards' look: only cards.bin.gz again)
            scene_pack.Out(scene).gz("cards.bin.gz", scene_pack.cards_blob(conf.get("greeting") or "Have a magical day!", card_style))
    elif card_style: raise ValueError("this scene isn't made from a photo: its cards are its own")
    tp = os.path.join(scene, "theme.json"); theme = json.load(open(tp))
    if cards: theme["cards"] = dict(scene_pack.CARDS, **dict(theme.get("cards") or {}, **{k: v for k, v in cards.items() if v is not None}))
    if horizon is not None: theme["horizon"] = int(horizon)
    with open(tp + ".tmp", "w") as f: json.dump(theme, f, indent=1)
    os.replace(tp + ".tmp", tp)


# ---------------------------------------------------------------- what each pixel is (segment.py's model)
AIENV = os.path.join(HERE, "work", "aienv", "bin", "python")
WATER_KINDS = ("water", "sea", "river", "lake", "fountain", "swimming pool", "waterfall")
WALL_KINDS = ("building", "wall", "house", "skyscraper", "tower", "column", "door", "windowpane", "arcade", "fence")


def segmentation(work):
    """(kinds picture, {number: name}) for work/day.png, from the model (cached beside it: segment.png, its
    labels in segment.json; made again when day.png is newer); None if the AI environment isn't there or the
    model fails (the finders then go by colour and texture)."""
    import subprocess
    day, png, js = (os.path.join(work, f) for f in ("day.png", "segment.png", "segment.json"))
    fresh = os.path.exists(png) and os.path.exists(js) and os.path.getmtime(png) >= os.path.getmtime(day)
    if not fresh:
        if not os.path.exists(AIENV) or os.environ.get("PHOTO_SCENE_NO_AI"): return None
        try: r = subprocess.run([AIENV, os.path.join(HERE, "segment.py"), day, png, js], capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired: print("segment: the model took too long: by colour instead"); return None
        if r.returncode or not os.path.exists(png):
            print("segment: the model didn't run (%s): by colour instead" % (r.stderr.strip().splitlines() or ["?"])[-1]); return None
    try: return Image.open(png).convert("L"), {int(k): v for k, v in json.load(open(js))["labels"].items()}
    except (OSError, ValueError): return None


def kinds_mask(seg, names):
    """255 where the model saw any of these kinds of thing."""
    img, labels = seg
    ids = {i for i, n in labels.items() if n in names}
    return img.point(lambda v: 255 if v in ids else 0)


def find_windows(day, notsky, walls=None):
    """[(x0, y0, x1, y1)]: dark patches in a plain, brighter wall (a daytime photo's windows), or bright warm
    ones (lit windows, at dusk or night). The wall: right round it, plain and clearly different; further
    out (6 to 12 px), stone-coloured (grey, cream, pink, sandstone: not leaves, not the sky through
    branches) and mostly calm (a tree is busy all round)."""
    g = day.convert("L"); hsv = day.convert("HSV")
    busy = ImageChops.difference(g, g.filter(ImageFilter.GaussianBlur(1.5))).load()
    wp = walls.filter(ImageFilter.MaxFilter(5)).load() if walls else None     # (the model's buildings and walls, a little wider)
    def stone(h, s, v): return s < 55 or h <= 30 or h >= 225
    def in_a_wall(x0, y0, x1, y1):
        pts = [(x, y) for y in range(max(0, y0 - 12), min(H, y1 + 13)) for x in range(max(0, x0 - 12), min(W, x1 + 13))
               if not (x0 - 5 <= x <= x1 + 5 and y0 - 5 <= y <= y1 + 5)]
        if not pts: return False
        return (sum(1 for x, y in pts if stone(*hp[x, y])) >= 0.92 * len(pts)
                and sum(1 for x, y in pts if busy[x, y] < 7) >= 0.25 * len(pts))
    local = g.filter(ImageFilter.BoxBlur(7))
    gp, lp, mp, hp = g.load(), local.load(), notsky.load(), hsv.load()
    found = []
    for kind in ("dark", "lit"):
        on = [[False] * W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                if mp[x, y] < 128: continue
                h, s, v = hp[x, y]
                if kind == "dark":
                    if 30 <= h <= 110 and s > 60: continue                    # (leaves)
                    on[y][x] = gp[x, y] < lp[x, y] - 18
                else:
                    on[y][x] = gp[x, y] > lp[x, y] + 22 and (h <= 45 or h >= 240) and s > 70 and v > 150   # (warm lamplight)
        seen = [[False] * W for _ in range(H)]
        for y0 in range(H):
            for x0 in range(W):
                if not on[y0][x0] or seen[y0][x0]: continue
                stack, pts = [(x0, y0)], []; seen[y0][x0] = True
                while stack:
                    x, y = stack.pop(); pts.append((x, y))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < W and 0 <= ny < H and on[ny][nx] and not seen[ny][nx]: seen[ny][nx] = True; stack.append((nx, ny))
                if not (5 <= len(pts) <= 500): continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                x0_, y0_, x1_, y1_ = min(xs), min(ys), max(xs), max(ys)
                bw, bh = x1_ - x0_ + 1, y1_ - y0_ + 1
                if bh < 2 or bw < 2 or not (0.2 <= bw / bh <= 3.5) or len(pts) / (bw * bh) < 0.5: continue
                ring = [gp[x, y] for y in range(max(0, y0_ - 3), min(H, y1_ + 4)) for x in range(max(0, x0_ - 3), min(W, x1_ + 4))
                        if not (x0_ <= x <= x1_ and y0_ <= y <= y1_)]
                inner = sum(gp[x, y] for x, y in pts) / len(pts)
                rm = sum(ring) / len(ring); rsd = (sum((v - rm) ** 2 for v in ring) / len(ring)) ** 0.5
                if rsd > 26 or abs(rm - inner) < 20: continue
                if wp is not None:                                          # (the model's say: on a building, not a tree)
                    if not wp[(x0_ + x1_) // 2, (y0_ + y1_) // 2]: continue
                elif not in_a_wall(x0_, y0_, x1_, y1_): continue
                found.append((x0_, y0_, x1_, y1_, kind))
    return found


def find_windows_into(work, scene):
    """Windows found in the day picture (find_windows) as the base the painting goes over (windows_base.png),
    and the lights redone. How many found, and how many windows lit in all."""
    from PIL import ImageDraw
    day = Image.open(os.path.join(work, "day.png")).convert("RGB")
    notsky = Image.open(os.path.join(work, "mask.png")).convert("L")
    seg = segmentation(work)
    found = find_windows(day, notsky, kinds_mask(seg, WALL_KINDS) if seg else None)
    base = Image.new("L", (W, H), 0); d = ImageDraw.Draw(base)
    for x0, y0, x1, y1, _ in found: d.rectangle([x0, y0, x1, y1], fill=255)
    base.save(os.path.join(work, "windows_base.png"))
    return len(found), rewindow(work, scene)


def clear_found_windows(work, scene):
    """All the windows gone: those found automatically and those painted. How many windows lit (none)."""
    for f in ("windows_base.png", "windows_edits.json"):
        if os.path.exists(os.path.join(work, f)): os.remove(os.path.join(work, f))
    return rewindow(work, scene)


def region_picture(work, kind):
    """A painted region (kind "windows" or "water") from the edits made in the previewer
    (work/<kind>_edits.json: [{"paint": [[x, y, r], ...]}, {"rect": [x0, y0, x1, y1]}, {"erase": [...]}, ...],
    in order), over <kind>_base.png if there is one (found automatically, or a render's), else nothing."""
    from PIL import ImageDraw
    base = os.path.join(work, kind + "_base.png")
    img = Image.open(base).convert("L").resize((W, H)) if os.path.exists(base) else Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    try: edits = json.load(open(os.path.join(work, kind + "_edits.json")))
    except (OSError, ValueError): edits = []
    for e in edits:
        for x, y, r in e.get("paint", []): d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        for x, y, r in e.get("erase", []): d.ellipse([x - r, y - r, x + r, y + r], fill=0)
        if e.get("rect"): x0, y0, x1, y1 = e["rect"]; d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], fill=255)
    return img


def windows_picture(work): return region_picture(work, "windows")


def frame_picture_from_edits(work):
    """The Frame brush's strokes (windows_edits.json {"frame": [[x, y, r], ...]}): white where a window's
    frame is, in front of its light; None if there are none."""
    from PIL import ImageDraw
    try: edits = json.load(open(os.path.join(work, "windows_edits.json")))
    except (OSError, ValueError): edits = []
    strokes = [e["frame"] for e in edits if e.get("frame")]
    boxes = [e["behind"] for e in edits if e.get("behind")]
    if not strokes and not boxes: return None
    img = Image.new("L", (W, H), 0); d = ImageDraw.Draw(img)
    for st in strokes:
        for x, y, r in st: d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    if boxes:                                                            # ("Behind": a box's dark parts are the frame)
        lum = Image.open(os.path.join(work, "day.png")).convert("L").resize((W, H), Image.LANCZOS)
        for b in boxes:
            img = ImageChops.lighter(img, frame_in_box(lum, b))
    return img


def frame_in_box(lum, box):
    """In a box drawn round a lantern or a window ("Behind"), its frame: the darkest of the three tones the
    box splits into on the day photo (black ironwork; glass, grey or bright), eased over a few levels so its
    edges aren't jagged. White where the frame is, the picture's size."""
    x0, y0, x1, y1 = box; x0, x1 = sorted((max(0, x0), min(W - 1, x1))); y0, y1 = sorted((max(0, y0), min(H - 1, y1)))
    out = Image.new("L", (W, H), 0)
    if x1 - x0 < 2 or y1 - y0 < 2: return out
    # (the photo's speckle and JPEG blocks smoothed first, a few pixels round the box too, so edges come out clean)
    pad = 3
    part = lum.crop((x0 - pad, y0 - pad, x1 + 1 + pad, y1 + 1 + pad)).filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.GaussianBlur(0.6))
    part = part.crop((pad, pad, part.width - pad, part.height - pad)); hist = part.histogram()
    # three tones, not two (black iron, glass that reflects grey by day, glass that's bright): the split into
    # three with the most spread between them (Otsu's, two thresholds), and the frame is only the darkest
    n = [0] * 257; m = [0] * 257
    for i in range(256): n[i + 1] = n[i] + hist[i]; m[i + 1] = m[i] + i * hist[i]
    def part_of(a, b):                                                   # (pixels a..b-1: their count and mean)
        c = n[b] - n[a]; return c, ((m[b] - m[a]) / c if c else 0)
    mu = m[256] / n[256]; best, t = -1, 128
    for t1 in range(1, 255):
        c1, m1 = part_of(0, t1)
        if not c1: continue
        for t2 in range(t1 + 1, 256):
            c2, m2 = part_of(t1, t2); c3, m3 = part_of(t2, 256)
            if not c2 or not c3: continue
            between = c1 * (m1 - mu) ** 2 + c2 * (m2 - mu) ** 2 + c3 * (m3 - mu) ** 2
            if between > best: best, t = between, t1
    soft = 12                                                            # (eased over this many levels either side)
    m = part.point(lambda v: 255 if v <= t - soft else 0 if v >= t + soft else int(255 * (t + soft - v) / (2 * soft)))
    m = m.filter(ImageFilter.MedianFilter(3))                           # (single stray pixels: gone)
    out.paste(m, (x0, y0))
    return out


def rewindow(work, scene):
    """After a window edit in the previewer: windows.png again from the edits, and the scene's lights.bin.gz
    (nothing else rebuilt). How many windows."""
    sp = os.path.join(work, "scene.json"); conf = json.load(open(sp))
    try: edits = json.load(open(os.path.join(work, "windows_edits.json")))
    except (OSError, ValueError): edits = []
    fixed = conf.get("lights_fixed") and os.path.join(work, conf["lights_fixed"])
    if fixed and os.path.exists(fixed) and not edits:               # (every edit undone: its own lights again, as made)
        for f in ("windows.png", "window_frame.png", "window_groups.json"):
            if os.path.exists(os.path.join(work, f)): os.remove(os.path.join(work, f))
        blob = gzip.open(fixed).read(); scene_pack.Out(scene).gz("lights.bin.gz", blob)
        return struct.unpack("<II", blob[4:12])[1] - 1
    if not conf.get("windows_painted"): conf["windows_painted"] = True; json.dump(conf, open(sp, "w"), indent=1)
    img = windows_picture(work); img.save(os.path.join(work, "windows.png"))
    frame = frame_picture_from_edits(work)
    fp = os.path.join(work, "window_frame.png")
    if frame is not None: frame.save(fp)
    elif os.path.exists(fp): os.remove(fp)
    try: groups = [e["group"] for e in json.load(open(os.path.join(work, "windows_edits.json"))) if e.get("group")]
    except (OSError, ValueError): groups = []
    gp = os.path.join(work, "window_groups.json")
    if groups: json.dump(groups, open(gp, "w"))
    elif os.path.exists(gp): os.remove(gp)
    blob, _, n = scene_pack.window_lights(img, tuple(conf.get("light", (255, 168, 80))), thin=False, frame=frame, groups=groups)
    scene_pack.Out(scene).gz("lights.bin.gz", blob)
    return n


def rewater(work, scene):
    """After a water edit: water.png again, the scene's water.raw.gz, and its theme.json (the "water"
    effect on or off, its strength and speed). How much of the screen is water (percent)."""
    img = region_picture(work, "water"); img.save(os.path.join(work, "water.png"))
    on = scene_pack.water_into(work, scene)
    try: conf = json.load(open(os.path.join(work, "scene.json")))
    except (OSError, ValueError): conf = {}
    tp = os.path.join(scene, "theme.json"); theme = json.load(open(tp))
    fx = [e for e in theme.get("effects", []) if e != "water"] + (["water"] if on else [])
    theme["effects"] = fx
    if on: theme["water"] = {"strength": conf.get("water", {}).get("strength", 1.0), "speed": conf.get("water", {}).get("speed", 1.0)}
    else: theme.pop("water", None)
    with open(tp + ".tmp", "w") as f: json.dump(theme, f, indent=1)
    os.replace(tp + ".tmp", tp)
    return round(100 * sum(1 for v in img.getdata() if v > 127) / (W * H), 1)


def set_water(work, scene, strength=None, speed=None):
    sp = os.path.join(work, "scene.json"); conf = json.load(open(sp))
    w = dict(conf.get("water") or {})
    if strength is not None: w["strength"] = float(strength)
    if speed is not None: w["speed"] = float(speed)
    conf["water"] = w; json.dump(conf, open(sp, "w"), indent=1)
    return rewater(work, scene)


def find_water(day, notsky, horizon):
    """Where a photo's water is (white), a guess: below the horizon, blue to green (the sky's colour on it,
    or a lagoon's), fairly smooth (not leaves, not a lawn's texture), in patches big enough to be a lake or
    the sea; what touches the bottom or spreads wide is likelier water."""
    g = day.convert("L"); hsv = day.convert("HSV")
    detail = ImageChops.difference(g, g.filter(ImageFilter.GaussianBlur(2))).filter(ImageFilter.BoxBlur(3))
    hp, dp, mp = hsv.load(), detail.load(), notsky.load()
    on = Image.new("L", (W, H), 0); op = on.load()
    for y in range(max(0, int(horizon) - 4), H):
        for x in range(W):
            h, s_, v = hp[x, y]
            if mp[x, y] < 128 and y < horizon + 15: continue                 # (sky just below the horizon line: a gap between things; lower
                                                                              #  down "sky" in the mask can be a sea that matches it)
            if 95 <= h <= 180 and s_ > 75 and v > 40 and dp[x, y] < 14: op[x, y] = 255     # (strongly coloured: shade on white is only faintly blue)
    on = on.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))        # (close small gaps: glints, ripples)
    # keep the big patches only
    px = on.load(); seen = bytearray(W * H); out = Image.new("L", (W, H), 0); outp = out.load()
    for y0 in range(H):
        for x0 in range(W):
            if not px[x0, y0] or seen[y0 * W + x0]: continue
            stack, pts = [(x0, y0)], []; seen[y0 * W + x0] = 1
            while stack:
                x, y = stack.pop(); pts.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and px[nx, ny] and not seen[ny * W + nx]: seen[ny * W + nx] = 1; stack.append((nx, ny))
            xs = [p[0] for p in pts]
            if len(pts) >= 1500 or (len(pts) >= 400 and max(xs) - min(xs) > 120):
                for x, y in pts: outp[x, y] = 255
    return out


def find_water_into(work, scene):
    """The water the model sees (its water, sea, river, lake, fountain, pool), small specks left out; by
    colour and texture (find_water) if the model isn't there."""
    seg = segmentation(work)
    if seg:
        w = kinds_mask(seg, WATER_KINDS).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    else:
        day = Image.open(os.path.join(work, "day.png")).convert("RGB")
        notsky = Image.open(os.path.join(work, "mask.png")).convert("L")
        w = find_water(day, notsky, json.load(open(os.path.join(work, "scene.json"))).get("horizon", H // 2))
    w.save(os.path.join(work, "water_base.png"))
    return rewater(work, scene)


def clear_found_water(work, scene):
    """All the water gone: found automatically and painted."""
    for f in ("water_base.png", "water_edits.json"):
        if os.path.exists(os.path.join(work, f)): os.remove(os.path.join(work, f))
    return rewater(work, scene)


def set_window_light(work, scene, colour):
    sp = os.path.join(work, "scene.json"); conf = json.load(open(sp))
    conf["light"] = list(colour); json.dump(conf, open(sp, "w"), indent=1)
    return rewindow(work, scene)


def found_outline(work, kind):
    """What was found automatically, drawn for a moment over the picture (the previewer fades it out): a
    transparent 800x480 PNG (bytes), outlines and a faint fill. kind: "sky" (where the photo's sky ends),
    "orb" (the sphere's circle and its lights), "windows", "water" (all of it: found and painted)."""
    import io
    from PIL import ImageDraw
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(out)
    def region(path, colour):
        if not os.path.exists(path): return
        m = Image.open(path).convert("L").resize((W, H)).point(lambda v: 255 if v > 127 else 0)
        edge = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(5)), m.filter(ImageFilter.MinFilter(3)))   # (3 px: easy to see)
        out.paste(Image.new("RGBA", (W, H), colour + (60,)), mask=m)               # (a faint fill: small windows show)
        out.paste(Image.new("RGBA", (W, H), colour + (255,)), mask=edge)
    if kind == "sky":
        m = os.path.join(work, "mask.png")
        if os.path.exists(m):                                              # (the edge between sky and the rest)
            sky = Image.open(m).convert("L").resize((W, H)).point(lambda v: 0 if v > 127 else 255)
            edge = ImageChops.subtract(sky.filter(ImageFilter.MaxFilter(5)), sky.filter(ImageFilter.MinFilter(3)))
            out.paste(Image.new("RGBA", (W, H), (120, 200, 255, 255)), mask=edge)
    elif kind == "orb":
        try:
            conf = json.load(open(os.path.join(work, "scene.json"))); o = conf.get("orb")
            if o: d.ellipse([o["cx"] - o["r"], o["cy"] - o["r"], o["cx"] + o["r"], o["cy"] + o["r"]], outline=(255, 70, 200, 255), width=3)
            for x, y in json.load(open(os.path.join(work, "twinkle_points.json"))):
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 70, 200, 255))
        except (OSError, ValueError): pass
    elif kind == "windows": region(os.path.join(work, "windows.png"), (255, 190, 80))   # (all of them: found and painted)
    elif kind == "water": region(os.path.join(work, "water.png"), (60, 210, 255))
    buf = io.BytesIO(); out.save(buf, "PNG"); return buf.getvalue()


PHOTO_FILES = ("day.png", "dusk.png", "night.png", "mask.png", "scene.json", "twinkle_mask.png", "twinkle_points.json",
               "twinkle_found.json", "erase.json", "erase_groups.json", "edits.json", "windows.png",
               "windows_base.png", "windows_edits.json", "window_frame.png", "window_groups.json", "water.png", "water_base.png", "water_edits.json",
               "segment.png", "segment.json")


def main():
    ap = argparse.ArgumentParser(description="A countdown app's scene from one daytime photo: try photos (--try), keep one (--keep).",
                                 epilog="e.g. photo_scene.py ~/Desktop/photo.jpg epcot --try --orb auto, then photo_scene.py --keep NAME epcot")
    ap.add_argument("args", nargs="+", help="PHOTO APP; or APP with --keep, --back, --list")
    ap.add_argument("--try", dest="trial", action="store_true", help="a trial: build/trial/APP/<photo's name>/, shown by the previewer; the app's unchanged")
    ap.add_argument("--keep", metavar="NAME", help="put that trial in the app (the photo's name, as --list shows it)")
    ap.add_argument("--back", action="store_true", help="the previewer back to the app's own scene")
    ap.add_argument("--list", action="store_true", help="the trials so far")
    ap.add_argument("--crop", help="X,Y,W,H of the part of the photo to use, in its pixels (5:3 is best)")
    ap.add_argument("--orb", help="auto (found in the photo), or CX,CY,R: the sphere's circle on the 800x480 screen: its lights, and never sky")
    ap.add_argument("--keep-mask", action="store_true", help="use the work folder's mask.png as it is (painted by hand)")
    ap.add_argument("--no-preview", action="store_true", help="don't open (or switch) the previewer")
    a = ap.parse_args()
    # the arguments in any order: an app's name, and (to make a scene) a photo; the app, if it's left out,
    # the one tried last
    def is_app(x): return os.path.isfile(os.path.join(REPO, "apps", x, "app.json")) and "scene" in json.load(open(os.path.join(REPO, "apps", x, "app.json")))
    named = [x for x in a.args if is_app(x)]
    files = [x for x in a.args if x not in named and os.path.isfile(os.path.expanduser(x))]
    for x in a.args:
        if x not in named and x not in files:
            if "<" in x or ">" in x or x.isupper(): sys.exit("photo_scene: %r is a placeholder from an example: put the photo's path there" % x)
            sys.exit("photo_scene: %s is neither a photo here nor a countdown app (%s)" % (x, ", ".join(sorted(n for n in os.listdir(os.path.join(REPO, "apps")) if is_app(n)))))
    if named: app = named[0]
    else:
        tried = sorted((os.path.getmtime(os.path.join(REPO, "build", "trial", n, "current")), n) for n in
                       (os.listdir(os.path.join(REPO, "build", "trial")) if os.path.isdir(os.path.join(REPO, "build", "trial")) else [])
                       if os.path.exists(os.path.join(REPO, "build", "trial", n, "current")) and is_app(n))
        if not tried: sys.exit("photo_scene: which app is it for? e.g. photo_scene.py PHOTO epcot --try")
        app = tried[-1][1]; print("(for %s, the app tried last)" % app)
    app_dir = os.path.join(REPO, "apps", app)
    meta = json.load(open(os.path.join(app_dir, "app.json")))
    out = os.path.join(app_dir, meta["scene"]["dir"], meta["scene"]["default"])
    app_work = os.environ.get("THEME_WORK") or os.path.join(HERE, "work", app)
    root = trial_root(app)
    if a.list:
        cur = open(os.path.join(root, "current")).read().strip() if os.path.exists(os.path.join(root, "current")) else ""
        for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            if os.path.isdir(os.path.join(root, n)): print(("* " if n == cur else "  ") + n + "   " + os.path.relpath(os.path.join(root, n, "scene", "preview.png"), REPO))
        return
    if a.back:
        set_current(app, ""); print("preview: %s's own scene" % app)
        if not a.no_preview: open_preview(app)
        return
    if a.keep:
        try: keep_trial(app, a.keep)
        except ValueError: sys.exit("photo_scene: no trial %s (see --list)" % a.keep)
        print("kept: %s is %s's scene now (deploy it: tools/board/deploy.py %s)" % (a.keep, app, app))
        if not a.no_preview: open_preview(app)
        return
    if not files: sys.exit("photo_scene: no photo given (its path, e.g. ~/Desktop/spaceship-earth.jpg)")
    photo = files[0]
    crop = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    orb = None
    if a.orb == "auto": orb = "auto"
    elif a.orb:
        try: orb = tuple(int(v) for v in a.orb.split(","))
        except ValueError: orb = ()
        if len(orb) != 3: sys.exit("photo_scene: --orb is auto, or three numbers: the sphere's centre and radius on the 800x480 screen, e.g. --orb 534,170,218")
    if a.trial:
        name = try_photo(app, photo, orb, crop, a.keep_mask)
        print("trying %s (%s)\nkeep it: photo_scene.py --keep %s %s" % (
            name, os.path.relpath(os.path.join(root, name, "scene", "preview.png"), REPO), name, app))
        if not a.no_preview: open_preview(app)
    else:
        make(photo, app_work, out, crop, orb, a.keep_mask)
        print("see it: python3 tools/preview/preview.py %s   (or %s)" % (app, os.path.relpath(os.path.join(out, "preview.png"), REPO)))


if __name__ == "__main__":
    main()
