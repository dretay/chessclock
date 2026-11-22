"""Window-light mask for the photo version of the mockup (panel A): which pixels of
assets/dream/panel_photo.jpg are window glass, so the page can switch them on at night.

Writes THEME_WORK/mockup/winA.png (white = glass).

Cabin windows: pixels a little darker than their surroundings, inside the cabin zones
(not the funnels, not forward of the round portholes). The big forward windows are
filled solid instead: the darker-than-surroundings test only finds the top and bottom
edges of a wide dark pane, which would light as two thin lines."""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "dream"))
OUT = os.path.join(os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "dream")), "mockup")
os.makedirs(OUT, exist_ok=True)

W, H = 800, 480
im = Image.open(os.path.join(ASSETS, "panel_photo.jpg")).convert("RGB").resize((W, H)); px = im.load()
L = im.convert("L"); bl = L.filter(ImageFilter.BoxBlur(3)).load(); lp = L.load()

# ---- cabin windows, in the cabin zones only
ZONES = [[(68,213),(440,200),(441,258),(320,259),(320,256),(68,258)],
         [(440,200),(592,204),(606,232),(612,272),(560,280),(500,290),(420,290),(441,258)]]
z = Image.new("L", (W, H), 0); zd = ImageDraw.Draw(z)
for p in ZONES: zd.polygon(p, fill=255)
zp = z.load()
win = Image.new("L", (W, H), 0); wp = win.load()
for y in range(H):
    for x in range(W):
        if zp[x, y]:
            r, g, b = px[x, y]
            if bl[x, y] > 110 and lp[x, y] < bl[x, y] * 0.86 and max(r, g, b) - min(r, g, b) < 70: wp[x, y] = 255

# ---- the forward glass (bridge rows and the three front strips): solid panes
POLY = [(38,302),(40,272),(50,250),(62,212),(110,190),(120,166),(160,163),(163,138),(212,138),(214,158),(268,158),(270,136),(334,136),(336,163),(378,163),(381,130),(397,130),(402,158),(470,160),(485,153),(520,158),(560,178),(576,195),(593,224),(611,261),(719,261),(724,243),(736,254),(776,281),(742,310),(692,350),(642,372),(620,371),(500,362),(400,352),(300,341),(200,329),(100,315),(60,309)]
FRONT = [(478,198),(596,200),(614,276),(530,278),(478,232)]
zone = Image.new("L", (W, H), 0); ImageDraw.Draw(zone).polygon(FRONT, fill=255)
ship = Image.new("L", (W, H), 0); ImageDraw.Draw(ship).polygon(POLY, fill=255)
fz, sp = zone.load(), ship.load()
add = Image.new("L", (W, H), 0); ap = add.load()
for y in range(H):
    for x in range(W):
        if fz[x, y] and sp[x, y]:
            r, g, b = px[x, y]
            # dark grey glass; above the strips the blue sea is behind, so blue is excluded there;
            # 228-237 is the shadow under the deck overhang, not glass
            if r*0.3 + g*0.59 + b*0.11 < 118 and (b - r < 38 or y >= 238) and not (228 <= y <= 237): ap[x, y] = 255
add = add.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))     # close the mullion gaps
ap = add.load()
for y in range(238, H):            # the strips end at the superstructure's forward edge: (587,245)-(607,270)
    for x in range(W):
        if x > 587 + (y - 245) * 0.8 - 1.5: ap[x, y] = 0
for y in range(H):
    for x in range(W):
        if fz[x, y]: wp[x, y] = 255 if (ap[x, y] > 128 and sp[x, y]) else 0
for y in range(222, 240):          # a stray speck out over the sea
    for x in range(598, 640): wp[x, y] = 0
win.save(os.path.join(OUT, "winA.png"), optimize=True)

# ---- the light itself (litA.png, added on top at night, per window cell). Built from the photo, not a flat
# colour: by day the glass is dark and the frames are white, so lit from inside it's the other way round:
# brightness = how much darker than its surroundings each pixel is. The frames and mullions go dark, portholes
# stay round with soft edges, and the forward panes keep the photo's perspective. Each window gets a slightly
# different warm tint.
import random
random.seed(7)
TINTS = [(255,196,120),(255,206,140),(255,184,104),(255,226,180),(255,238,214)]
grow = win.filter(ImageFilter.MaxFilter(3))                 # include the glass's soft edge
gp = grow.load()
bl2 = L.filter(ImageFilter.BoxBlur(5)).load()
lit = Image.new("RGB", (W, H), (0, 0, 0)); lq = lit.load()
# one tint per window: label the connected panes
label = {}; tint_of = []
for y0 in range(H):
    for x0 in range(W):
        if gp[x0, y0] and (x0, y0) not in label:
            n = len(tint_of); tint_of.append(TINTS[4] if random.random() < 0.1 else TINTS[random.randrange(4)])
            stack = [(x0, y0)]; label[(x0, y0)] = n
            while stack:
                x, y = stack.pop()
                for q in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
                    if 0 <= q[0] < W and 0 <= q[1] < H and gp[q] and q not in label: label[q] = n; stack.append(q)
for y in range(H):
    for x in range(W):
        if not gp[x, y]: continue
        surround = max(bl[x, y], bl2[x, y], 1)
        d = max(0.0, min(1.0, (surround - lp[x, y]) / (surround * 0.45)))   # 0 = frame-white, 1 = deep glass
        if fz[x, y]: d = max(0.0, min(1.0, (150 - lp[x, y]) / 90.0))     # the big forward panes: by their own darkness
        a = d ** 0.8
        tr, tg, tb = tint_of[label[(x, y)]]
        lq[x, y] = (int(tr * a), int(tg * a), int(tb * a))
lit = lit.filter(ImageFilter.GaussianBlur(0.6))            # soften to the photo's own sharpness
lit.save(os.path.join(OUT, "litA.png"), optimize=True)

# ---- which pixels switch together (cellsA.png: id = R*256 + G, 0 = not a window). A window that is one
# pane (a forward strip, a porthole, a single cabin window) switches as a whole. Big connected areas (whole
# rows of balcony glass) are split along their own structure: the bright glass between the dark frames is
# found, very long panes are cut into room-width slices, and the soft edges go to the nearest pane. (Fixed
# blocks would show as squares.)
from collections import deque
box = {}
for (x, y), n in label.items():
    b = box.get(n); box[n] = (x, y, x, y) if b is None else (min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y))
whole = {n for n, (x0, y0, x1, y1) in box.items() if (x1 - x0 <= 12 and y1 - y0 <= 10) or fz[(x0 + x1) // 2, (y0 + y1) // 2]}
ids = {}
def cell_id(key):
    if key not in ids: ids[key] = len(ids) + 1
    return ids[key]
assign = {}
for (x, y), n in label.items():
    if lq[x, y] != (0, 0, 0) and n in whole: assign[(x, y)] = cell_id(("w", n))
# the bright cores of the big areas, as 4-connected panes
core = {(x, y) for (x, y), n in label.items() if n not in whole and sum(lq[x, y]) > 0.5 * sum(tint_of[n])}
seen = set()
for start in core:
    if start in seen: continue
    comp = []; q = deque([start]); seen.add(start)
    while q:
        x, y = q.popleft(); comp.append((x, y))
        for nb in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
            if nb in core and nb not in seen: seen.add(nb); q.append(nb)
    cx0 = min(c[0] for c in comp); cid = len(ids)
    for (x, y) in comp: assign[(x, y)] = cell_id(("c", cid, (x - cx0) // 12))     # long panes: 12 px rooms
# everything else lit in the big areas: the nearest pane in the same area
q = deque(pt for pt in assign if label[pt] not in whole)
while q:
    x, y = q.popleft()
    for nb in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
        if nb in label and nb not in assign and label[nb] == label[(x, y)] and lq[nb] != (0, 0, 0):
            assign[nb] = assign[(x, y)]; q.append(nb)
cells = Image.new("RGB", (W, H)); cq = cells.load()
for (x, y), i in assign.items(): cq[x, y] = (i >> 8, i & 255, 0)
cells.save(os.path.join(OUT, "cellsA.png"), optimize=True)
print("cellsA.png:", len(ids), "switchable windows")
print("litA.png written")
print("winA.png:", sum(1 for v in win.tobytes() if v))
