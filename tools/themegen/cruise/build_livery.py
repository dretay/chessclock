"""Turn the Dream side-profile photo (port side, bow left) into a side
elevation texture for the model: x along the ship (bow at +x), z height,
both in metres. The photo is warped piecewise so the bow, the funnels and
the stern line up with the model. Writes:
  elevation.png  RGBA, alpha = the photo shows ship here
  windows.png    L, window glass (for the night lights)
"""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "dream"))
OUT = os.path.join(os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "dream")), "livery")
os.makedirs(OUT, exist_ok=True)
PHOTO = os.path.join(ASSETS, "side.png")   # the Dream side-profile photo (port side, bow left)
X0, X1, Z0, Z1, RES = -172.0, 172.0, -1.0, 60.0, 0.1       # texture extent (m) and m/px
TW, TH = int((X1 - X0) / RES), int((Z1 - Z0) / RES)

# model x (m) -> photo u (px), at the bow tip, both funnels and the stern
KNOTS_U = [(170.0, 62), (137.9, 175), (0.0, 522), (-64.6, 692), (-170.0, 890)]
# vertical scale (photo px per metre) at the same stations: bow fitted to the bow deck,
# funnels to their tops
KNOTS_K = [(170.0, 3.27), (137.9, 3.0), (0.0, 2.5), (-64.6, 2.4), (-170.0, 2.3)]
def interp(knots, x):
    if x >= knots[0][0]: (xa, a), (xb, b) = knots[0], knots[1]
    elif x <= knots[-1][0]: (xa, a), (xb, b) = knots[-2], knots[-1]
    else:
        for (xa, a), (xb, b) in zip(knots, knots[1:]):
            if xb <= x <= xa: break
    return a + (b - a) * (x - xa) / (xb - xa)
def waterline(u):                    # photo waterline slopes from the bow to the stern
    return 358 + (345 - 358) * (u - 175) / (890 - 175)

# the ship's outline in the photo (sky and sea are left transparent)
OUTLINE = [(60, 302), (190, 296), (232, 280), (235, 245), (290, 232), (330, 226), (497, 222), (500, 208),
           (547, 208), (550, 225), (665, 225), (668, 210), (720, 210), (722, 235), (870, 240), (885, 255),
           (893, 310), (891, 348), (175, 362), (120, 332)]
NAME_BOX = (254, 319, 298, 335)      # "Disney DREAM" on the hull: mirrored back so it reads correctly

photo = Image.open(PHOTO).convert("RGB")
mask = Image.new("L", photo.size, 0); ImageDraw.Draw(mask).polygon(OUTLINE, fill=255)
pp, mp = photo.load(), mask.load()
PW, PH = photo.size

def sample(u, v):
    if u < 0 or v < 0 or u >= PW - 1 or v >= PH - 1: return (0, 0, 0, 0)
    x0, y0 = int(u), int(v); fx, fy = u - x0, v - y0
    out = []
    for c in range(3):
        a = pp[x0, y0][c] * (1 - fx) + pp[x0 + 1, y0][c] * fx
        b = pp[x0, y0 + 1][c] * (1 - fx) + pp[x0 + 1, y0 + 1][c] * fx
        out.append(int(a * (1 - fy) + b * fy))
    return (*out, 255 if mp[x0, y0] else 0)

tex = Image.new("RGBA", (TW, TH)); tp = tex.load()
name_px = []
for j in range(TH):
    z = Z1 - (j + 0.5) * RES                     # row 0 = top
    for i in range(TW):
        x = X0 + (i + 0.5) * RES
        u = interp(KNOTS_U, x); v = waterline(u) - z * interp(KNOTS_K, x)
        px_ = sample(u, v)
        r, g, b_, al = px_
        if al and x < -60 and b_ > r + 14 and (r + g + b_) > 330:   # sky showing past the stepped stern (only there: bluish glass forward isn't sky)
            px_ = (r, g, b_, 0)
        if x > 119.0 and z > 17.5: px_ = (px_[0], px_[1], px_[2], 0)
        tp[i, j] = px_
        if NAME_BOX[0] <= u <= NAME_BOX[2] and NAME_BOX[1] <= v <= NAME_BOX[3]: name_px.append((i, j))

# the photo is of the port side; the render shows starboard, so flip the name back
if name_px:
    i0 = min(p[0] for p in name_px); i1 = max(p[0] for p in name_px); j0 = min(p[1] for p in name_px); j1 = max(p[1] for p in name_px)
    box = (i0, j0, i1 + 1, j1 + 1)
    tex.paste(tex.crop(box).transpose(Image.FLIP_LEFT_RIGHT), box)
    print("name flipped in", box)

# ---- bow scrollwork and anchor ornament, from the high-resolution bow photo (port side, bow left)
BOW = Image.open(os.path.join(ASSETS, "bow.jpg")).convert("RGB"); bp = BOW.load()
def goldness(r, g, b):
    # gold by its warm tint (the shaded parts are dark, around 95,59,35), not by brightness
    if r < 55: return 0.0
    return max(0.0, min(1.0, min((r - b - 22) / 45.0, (g - b - 6) / 25.0)))
def tex_ij(x, z): return int((x - X0) / RES), int((Z1 - z) / RES)
def sunlit(r, g, b):   # the bow photo's gold is in shade: lift it to match the sunlit gold elsewhere
    return (min(255, int(r * 1.55)), min(255, int(g * 1.5)), min(255, int(b * 1.15)))
navy = tp[tex_ij(120, 7)]
# the scrollwork band in the photo: top and bottom edges at a few stations along it
STATIONS = [(530, 683, 750), (650, 679, 742), (800, 675, 718), (1000, 675, 697), (1035, 676, 692)]
def edges(xp):
    for (xa, ta, ba), (xb, tb, bb) in zip(STATIONS, STATIONS[1:]):
        if xa <= xp <= xb:
            f = (xp - xa) / (xb - xa); return ta + (tb - ta) * f, ba + (bb - ba) * f
    return STATIONS[-1][1], STATIONS[-1][2]
# where it goes on the model: from 139 m (aft end, where the plain stripe begins) to the bow tip,
# its top rising with the sheer; it is tall at the bow and tapers to the stripe aft
SX0, SX1 = 139.0, 166.5
def navy_top(x):   # the navy sweeps up from the stripe to the bow's knuckle (17 m on the model), then runs along it
    f = min(1.0, max(0.0, (x - 118.0) / 22.0))
    return 12.3 + (f * f * (3 - 2 * f)) * 4.6
# extend the navy up to that line (the side photo's white band lands too low on the model here)
for i in range(tex_ij(120.0, 0)[0], tex_ij(167.5, 0)[0]):
    x = X0 + (i + 0.5) * RES; zt = navy_top(x)
    for j in range(tex_ij(0, zt)[1], tex_ij(0, 11.0)[1]):
        r_, g_, b2, a_ = tp[i, j]
        if a_ and r_ + g_ + b2 > 300: tp[i, j] = navy[:3] + (255,)
def top_z(x): return navy_top(x) - 0.25          # the scrollwork follows the top of the navy
def height(x): return 0.9 + (x - SX0) / (SX1 - SX0) * 2.4
i0, _ = tex_ij(SX0, 0); i1, _ = tex_ij(SX1, 0)
for i in range(i0, i1):
    x = X0 + (i + 0.5) * RES
    t = (x - SX0) / (SX1 - SX0)                    # 0 at the aft end, 1 at the bow
    xp = 1035 - t * 505                            # photo column (the photo's bow is on the left)
    pt, pb = edges(xp)
    ztop, h = top_z(x), height(x)
    below = tp[i, tex_ij(0, ztop - h - 0.6)[1]]          # the hull's own colour just below the band
    local = below if (below[3] and sum(below[:3]) < sum(navy[:3]) + 40) else navy   # never foam or sea
    for j in range(tex_ij(0, ztop + 0.3)[1], tex_ij(0, ztop - h - 0.3)[1]):
        z = Z1 - (j + 0.5) * RES
        if tp[i, j][3] == 0: continue
        s = (ztop - z) / h                          # 0 at the top edge, 1 at the bottom
        base = local if -0.15 < s < 1.15 else tp[i, j]
        if 0 <= s <= 1:
            yp = pt + s * (pb - pt)
            r, g, bb_ = bp[int(xp), int(yp)]
            a = goldness(r, g, bb_); r, g, bb_ = sunlit(r, g, bb_)
            px_ = tuple(int(base[c] * (1 - a) + (r, g, bb_)[c] * a) for c in range(3)) + (255,)
        else:
            px_ = base[:3] + (255,)
        tp[i, j] = px_
# the anchor ornament: photo (1280..1352, 826..898) -> model centred at 141 m, 5 m up, 2.6 m across
AX, AZ, AS = 138.4, 5.0, 2.6
# paint out the blurry ornament from the side photo first
for i in range(*[tex_ij(AX - 2.2, 0)[0], tex_ij(AX + 2.2, 0)[0]]):
    for j in range(tex_ij(0, AZ + 2.2)[1], tex_ij(0, AZ - 2.2)[1]):
        old = tp[i, j]
        if old[3] and (goldness(*old[:3]) > 0.02 or sum(old[:3]) > sum(navy[:3]) + 60):   # only the old ornament's pixels
            side_px = tp[tex_ij(AX - 2.6, 0)[0], j]          # same height, just aft of it
            tp[i, j] = (side_px if (side_px[3] and sum(side_px[:3]) < sum(navy[:3]) + 40) else navy)[:3] + (255,)
ia0, ja0 = tex_ij(AX - AS / 2, AZ + AS / 2); ia1, ja1 = tex_ij(AX + AS / 2, AZ - AS / 2)
for i in range(ia0, ia1):
    for j in range(ja0, ja1):
        if tp[i, j][3] == 0: continue
        fx = (i - ia0) / (ia1 - ia0); fy = (j - ja0) / (ja1 - ja0)
        xp = 1352 - fx * 72; yp = 826 + fy * 72      # mirrored: port photo onto the starboard side
        r, g, bb_ = bp[int(xp), int(yp)]; a = goldness(r, g, bb_); r, g, bb_ = sunlit(r, g, bb_)
        under = tp[i, j]
        tp[i, j] = tuple(int(under[c] * (1 - a) + (r, g, bb_)[c] * a) for c in range(3)) + (255,)

# ---- a lone porthole ahead of the cluster's stepped forward edge (116 m, 19 m up): paint it out with the
# white plating around it
LX0, LX1, LZ0, LZ1 = 114.9, 117.9, 17.5, 20.4
ia, ja = tex_ij(LX0, LZ1); ib, jb = tex_ij(LX1, LZ0)
for i in range(ia, ib):                 # each column blends from the plating just above to just below
    top, bot = tp[i, ja - 2], tp[i, jb + 2]
    for j in range(ja, jb):              # (including pixels the sky test cut out: they'd leave a hole)
        f = (j - ja) / (jb - ja)
        tp[i, j] = tuple(int(top[c] * (1 - f) + bot[c] * f) for c in range(3)) + (255,)
# ---- lifeboats: the render hangs real 3D boats here, so paint the photo's flat ones out, leaving the
# shaded recess they hang in (otherwise the boats show twice, and look painted on)
BOAT_RUNS = [(-102.0, -85.6), (-82.5, -65.5), (-63.0, -50.2), (-48.1, -35.1), (-32.4, -19.0), (-16.3, -2.8), (0.4, 14.7), (18.3, 33.1)]
boat_out = set()
RZ0, RZ1, EDGE = 15.0, 20.9, 0.35          # the recess each boat hangs in, and its soft edge (m)
for (xa, xb) in BOAT_RUNS:
    xa -= 0.5; xb += 0.5
    ia, _ = tex_ij(xa, 0); ib, _ = tex_ij(xb, 0); _, ja = tex_ij(0, RZ1); _, jb = tex_ij(0, RZ0)
    for i in range(ia, ib):
        x = X0 + (i + 0.5) * RES
        for j in range(ja, jb):
            r, g, b_, a_ = tp[i, j]
            if not a_: continue
            z = Z1 - (j + 0.5) * RES
            # a deep, shaded opening: darkest up under the deck above, a little lighter toward its floor
            f = (z - RZ0) / (RZ1 - RZ0)
            sh = (int(78 - 44 * f), int(81 - 45 * f), int(89 - 45 * f))
            e = min(1.0, (x - xa) / EDGE, (xb - x) / EDGE, (z - RZ0) / EDGE, (RZ1 - z) / EDGE)
            tp[i, j] = tuple(int(sh[c] * e + (r, g, b_)[c] * (1 - e)) for c in range(3)) + (255,)
            boat_out.add((i, j))
print("lifeboats painted out:", len(boat_out), "px")
tex.save(os.path.join(OUT, "elevation.png"))

# window glass: darker than its surroundings, on the white superstructure, above the hull
L = tex.convert("L"); bl = L.filter(ImageFilter.BoxBlur(4)).load(); lp = L.load(); a = tex.getchannel("A").load()
win = Image.new("L", (TW, TH), 0); wp = win.load()
z_lo, z_hi = 16.0, 45.0          # cabin decks only: not the funnels or the top-deck clutter
X_FWD = 119.0                      # the forward edge of the round porthole cluster: no windows forward of it
for j in range(TH):
    z = Z1 - (j + 0.5) * RES
    if not (z_lo < z < z_hi): continue
    for i in range(TW):
        x = X0 + (i + 0.5) * RES
        if z > 38 and (abs(x) < 13 or abs(x + 64.6) < 13): continue
        if x > X_FWD: continue
        if (i, j) in boat_out: continue          # the recess behind the 3D lifeboats is not glass
        r, g, b, al = tp[i, j]
        if al and bl[i, j] > 105 and lp[i, j] < bl[i, j] * 0.84 and max(r, g, b) - min(r, g, b) < 70:
            wp[i, j] = 255
win.save(os.path.join(OUT, "windows.png"))
print("texture", TW, "x", TH)
