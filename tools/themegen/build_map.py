"""Make the fleet map on a desktop: NASA satellite imagery of the Caribbean (Blue Marble by day,
Black Marble's city lights at night) in Mercator, with the cruise ports marked, cut into tiles.
The board loads the few tiles around the ship it's following and draws the ships on top
(apps/cruise/map.py).

    python3 tools/themegen/build_map.py   -> apps/cruise/map/tiles/{day,night}/X_Y.rgb.gz and apps/cruise/map/map.json
    (the first run downloads about 20 pieces of imagery)

Tiles are 256x256 RGB, gzipped, kept for REGION only (beyond it the board shows plain ocean);
ones that are all one colour (open ocean) are just that colour in map.json.

Imagery from NASA GIBS (public domain; NASA asks for a credit, which the board shows), fetched once
into assets/map/nasa3857/:
    https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0
        &CRS=EPSG:3857&BBOX=...&WIDTH=...&HEIGHT=...&FORMAT=image/jpeg&LAYERS=<layer>
Needs assets/map/ne_50m_land.geojson (Natural Earth, public domain) to tell sea from land, and
assets/fonts/CormorantGaramond-SemiBold-Lining.ttf.
"""
import gzip, json, math, os, shutil, urllib.request
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ASSETS = os.path.join(REPO, "assets", "map")
NASA = os.path.join(ASSETS, "nasa3857")
FONT = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
OUT = os.path.join(REPO, "apps", "cruise", "map")

# the world: Mercator, 22528 px around the equator (about 63 px a degree of longitude, 70 a degree
# of latitude at Florida's: a screen is about 13 degrees across), from 72.5 N down to about 66 S, in
# 88 x 48 tiles
TILE, COLS, ROWS = 256, 88, 48
# only the Caribbean is kept (with the Gulf of Mexico, Florida and the Bahamas), and a margin so a
# ship at its edge still sees land around it: lon0, lat0, lon1, lat1
REGION = (-101.0, 5.0, -54.0, 36.5)
WW, WH = TILE * COLS, TILE * ROWS
LAT_TOP = 72.5
def merc(lat): return math.log(math.tan(math.pi / 4 + math.radians(max(-85.0, min(85.0, lat))) / 2))
MERC_TOP = merc(LAT_TOP)
K = WW / (2 * math.pi)                         # px per radian
def proj(lon, lat): return ((lon + 180) / 360 * WW, (MERC_TOP - merc(lat)) * K)
SCREEN_W, SCREEN_H = 800, 480

# cruise ports, marked on the imagery: name, lat, lon, where the name goes (r, l, a(bove), b(elow))
PORTS = [("Port Canaveral", 28.41, -80.60, "r"), ("Fort Lauderdale", 26.09, -80.12, "l"), ("Miami", 25.77, -80.17, "l"),
         ("Nassau", 25.06, -77.35, "b"), ("Castaway Cay", 26.08, -77.54, "r"), ("Lookout Cay", 24.62, -76.15, "r"),
         ("Galveston", 29.31, -94.80, "b"), ("New Orleans", 29.95, -90.07, "r"), ("Key West", 24.55, -81.80, "b"),
         ("Cozumel", 20.42, -86.92, "r"), ("Progreso", 21.28, -89.66, "a"), ("Grand Cayman", 19.29, -81.38, "b"),
         ("Falmouth", 18.49, -77.65, "b"), ("San Juan", 18.47, -66.11, "a"), ("St. Thomas", 18.34, -64.93, "b"),
         ("Tortola", 18.43, -64.62, "r"), ("St. Maarten", 18.02, -63.05, "r"), ("Antigua", 17.12, -61.85, "r"),
         ("St. Lucia", 14.01, -60.99, "r"), ("Barbados", 13.10, -59.62, "r"), ("Aruba", 12.52, -70.03, "b"),
         ("Curaçao", 12.11, -68.93, "r"), ("Cartagena", 10.40, -75.53, "b"), ("the Panama Canal", 9.08, -79.68, "b"),
         ("New York", 40.70, -74.01, "r"), ("Halifax", 44.65, -63.57, "r"), ("Bermuda", 32.30, -64.78, "r"),
         ("Vancouver", 49.29, -123.11, "r"), ("Seattle", 47.60, -122.34, "r"), ("Juneau", 58.30, -134.40, "r"),
         ("Skagway", 59.45, -135.32, "a"), ("Ketchikan", 55.34, -131.64, "r"), ("San Francisco", 37.80, -122.40, "l"),
         ("Los Angeles", 33.74, -118.27, "r"), ("San Diego", 32.71, -117.17, "b"), ("Ensenada", 31.85, -116.63, "r"),
         ("Cabo San Lucas", 22.89, -109.91, "r"), ("Puerto Vallarta", 20.65, -105.23, "r"), ("Honolulu", 21.30, -157.86, "r"),
         ("Barcelona", 41.38, 2.18, "r"), ("Rome", 42.09, 11.79, "r"), ("Naples", 40.84, 14.25, "r"), ("Marseille", 43.30, 5.37, "a"),
         ("Lisbon", 38.71, -9.14, "l"), ("Dover", 51.12, 1.31, "l"), ("Copenhagen", 55.68, 12.57, "r"), ("Bergen", 60.39, 5.32, "l"),
         ("Reykjavik", 64.15, -21.94, "r"), ("Singapore", 1.26, 103.82, "b"), ("Hong Kong", 22.30, 114.17, "r"),
         ("Yokohama", 35.45, 139.65, "r"), ("Sydney", -33.86, 151.21, "r"), ("Brisbane", -27.40, 153.10, "r"),
         ("Melbourne", -37.84, 144.93, "b"), ("Auckland", -36.84, 174.77, "r")]

GIBS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&CRS=EPSG:3857" \
       "&BBOX=%.2f,%.2f,%.2f,%.2f&WIDTH=%d&HEIGHT=%d&FORMAT=image/jpeg&LAYERS=%s"
R = 6378137.0
LAYERS = {   # name -> (GIBS layer, brightness, contrast, saturation, credit)
    "day": ("BlueMarble_NextGeneration", 1.05, 1.08, 1.05, "Imagery: NASA Blue Marble"),
    "night": ("VIIRS_Black_Marble", 1.15, 1.1, 1.0, "Imagery: NASA Black Marble"),
}
IVORY, PORT_TEXT, HALO = (244, 238, 222), (176, 186, 196), (4, 10, 22)


B = 2048                                          # the imagery comes in pieces this big


def block(layer, bx, by):
    """One B x B piece of a layer (downloaded once), at world pixel (bx, by)."""
    os.makedirs(NASA, exist_ok=True)
    w, h = min(B, WW - bx), min(B, WH - by); m = 2 * math.pi * R / WW      # metres a pixel
    path = os.path.join(NASA, "%s_%d_%d_%d.jpg" % (layer, WW, bx // B, by // B))
    if not os.path.exists(path):
        x0 = -math.pi * R + bx * m; y1 = MERC_TOP * R - by * m
        url = GIBS % (x0, y1 - h * m, x0 + w * m, y1, w, h, layer)
        for attempt in range(3):
            try: urllib.request.urlretrieve(url, path + ".tmp"); os.replace(path + ".tmp", path); break
            except OSError as e: print("  retrying", os.path.basename(path), e)
    return Image.open(path).convert("RGB")


C = 16                                            # sea/land is worked out in cells this big


def land_mask():
    """Land (255) and sea (0) for the whole world, a pixel per C x C cell, from Natural Earth."""
    mask = Image.new("L", (WW // C, WH // C)); d = ImageDraw.Draw(mask)
    for f in json.load(open(os.path.join(ASSETS, "ne_50m_land.geojson")))["features"]:
        g = f["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for i, ring in enumerate(poly):
                d.polygon([(x / C, y / C) for x, y in (proj(lon, lat) for lon, lat, *_ in ring)], fill=255 if i == 0 else 0)
    return mask


def reachable_tiles(mask):
    """Tiles some ship's view can show: within half a screen of the sea."""
    cw, ch = mask.size; sea = mask.load()
    # summed-area table of sea cells, so "any sea in this rectangle" is quick
    S = [[0] * (cw + 1) for _ in range(ch + 1)]
    for y in range(ch):
        row = 0
        for x in range(cw):
            row += sea[x, y] < 128; S[y + 1][x + 1] = S[y][x + 1] + row
    def any_sea(x0, y0, x1, y1):
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(cw, x1), min(ch, y1)
        return x1 > x0 and y1 > y0 and S[y1][x1] - S[y0][x1] - S[y1][x0] + S[y0][x0] > 0
    rx, ry = SCREEN_W // 2 // C + 1, SCREEN_H // 2 // C + 1; t = TILE // C
    keep = set()
    for ty in range(ROWS):
        for tx in range(COLS):
            x0, y0 = tx * t - rx, ty * t - ry; x1, y1 = (tx + 1) * t + rx, (ty + 1) * t + ry
            if any_sea(x0, y0, x1, y1) or any_sea(x0 + cw, y0, x1 + cw, y1) or any_sea(x0 - cw, y0, x1 - cw, y1):
                keep.add((tx, ty))
    return keep


def font(size): return ImageFont.truetype(FONT, size)


def port_sprites():
    """Each port as a small picture to lay over the imagery: a dot and its name with a soft dark
    halo. Returns [(RGBA image, world x, world y)] and the boxes they cover (for the ships' tags)."""
    f = font(16); out, boxes = [], []
    for name, lat, lon, side in PORTS:
        x, y = proj(lon, lat)
        anchor_xy, anchor = {"r": ((x + 6, y), "lm"), "l": ((x - 6, y), "rm"), "a": ((x, y - 6), "md"), "b": ((x, y + 6), "ma")}[side]
        bb = f.getbbox(name, anchor=anchor)
        box = [round(anchor_xy[0] + bb[0]) - 2, round(anchor_xy[1] + bb[1]) - 2, round(anchor_xy[0] + bb[2]) + 2, round(anchor_xy[1] + bb[3]) + 2]
        px0, py0 = int(min(box[0], x - 4)) - 12, int(min(box[1], y - 4)) - 12
        px1, py1 = int(max(box[2], x + 4)) + 12, int(max(box[3], y + 4)) + 12
        o = (-px0, -py0); at = (anchor_xy[0] + o[0], anchor_xy[1] + o[1])
        halo = Image.new("RGBA", (px1 - px0, py1 - py0)); ImageDraw.Draw(halo).text(at, name, font=f, fill=HALO + (255,), anchor=anchor)
        halo = halo.filter(ImageFilter.GaussianBlur(2)); halo.putalpha(halo.getchannel("A").point(lambda v: min(255, v * 2)))
        d = ImageDraw.Draw(halo)
        d.ellipse((x + o[0] - 2.4, y + o[1] - 2.4, x + o[0] + 2.4, y + o[1] + 2.4), fill=IVORY + (230,), outline=HALO + (255,))
        d.text(at, name, font=f, fill=PORT_TEXT + (255,), anchor=anchor)
        out.append((halo, px0, py0))
        boxes.append(box); boxes.append([round(x - 3), round(y - 3), round(x + 3), round(y + 3)])
    return out, boxes


def main():
    x0, y0 = proj(REGION[0], REGION[3]); x1, y1 = proj(REGION[2], REGION[1])
    keep = {(tx, ty) for tx, ty in reachable_tiles(land_mask())
            if x0 < (tx + 1) * TILE and tx * TILE < x1 and y0 < (ty + 1) * TILE and ty * TILE < y1}
    print("tiles a ship's view can reach: %d of %d" % (len(keep), COLS * ROWS))
    sprites, boxes = port_sprites()
    meta = {"tile": TILE, "cols": COLS, "rows": ROWS, "lat_top": LAT_TOP, "region": REGION, "layers": {}, "port_labels": boxes,
            "ports": [[n, la, lo] for n, la, lo, _ in PORTS]}
    tiles_dir = os.path.join(OUT, "tiles")
    if os.path.isdir(tiles_dir): shutil.rmtree(tiles_dir)
    for name, (layer, bright, contrast, sat, credit) in LAYERS.items():
        d = os.path.join(tiles_dir, name); os.makedirs(d); flat = {}; stored = size = 0; sea = None
        blocks = [(bx, by) for by in range(0, WH, B) for bx in range(0, WW, B)
                  if any((tx, ty) in keep for tx in range(bx // TILE, (bx + B) // TILE) for ty in range(by // TILE, (by + B) // TILE))]
        for i, (bx, by) in enumerate(blocks):
            print("\r%s: piece %d of %d" % (name, i + 1, len(blocks)), end="", flush=True)
            img = block(layer, bx, by)
            img = ImageEnhance.Color(ImageEnhance.Contrast(ImageEnhance.Brightness(img).enhance(bright)).enhance(contrast)).enhance(sat)
            img = img.convert("RGBA")
            for sp, sx, sy in sprites:                                      # the ports in this piece
                if sx < bx + img.width and sx + sp.width > bx and sy < by + img.height and sy + sp.height > by:
                    img.alpha_composite(sp, (sx - bx, sy - by)) if sx >= bx and sy >= by else \
                        img.alpha_composite(sp.crop((max(0, bx - sx), max(0, by - sy), sp.width, sp.height)), (max(0, sx - bx), max(0, sy - by)))
            img = img.convert("RGB")
            for ty in range(by // TILE, (by + img.height) // TILE):
                for tx in range(bx // TILE, (bx + img.width) // TILE):
                    if (tx, ty) not in keep: continue
                    t = img.crop((tx * TILE - bx, ty * TILE - by, (tx + 1) * TILE - bx, (ty + 1) * TILE - by))
                    lo, hi = zip(*t.getextrema())
                    if max(h - l for l, h in zip(lo, hi)) <= 6:            # all one colour: open ocean
                        flat["%d_%d" % (tx, ty)] = [(l + h) // 2 for l, h in zip(lo, hi)]; sea = sea or flat["%d_%d" % (tx, ty)]; continue
                    path = os.path.join(d, "%d_%d.rgb.gz" % (tx, ty))
                    with gzip.open(path, "wb", 9) as f: f.write(t.tobytes())
                    stored += 1; size += os.path.getsize(path)
            # a preview around Florida
            cx, cy = proj(-79.5, 26.5)
            if bx <= cx < bx + B and by <= cy < by + B and bx + B >= cx + 400 and by + B >= cy + 240 and cx - 400 >= bx and cy - 240 >= by:
                img.crop((int(cx - bx) - 400, int(cy - by) - 240, int(cx - bx) + 400, int(cy - by) + 240)).save(os.path.join(OUT, "preview_%s.png" % name))
        meta["layers"][name] = {"flat": flat, "sea": sea or [6, 10, 30], "credit": credit}
        print("\n%s: %d tiles stored (%.1f MB), %d flat" % (name, stored, size / 1e6, len(flat)))
    json.dump(meta, open(os.path.join(OUT, "map.json"), "w"), separators=(",", ":"))
    print("map ->", OUT)


if __name__ == "__main__":
    main()
