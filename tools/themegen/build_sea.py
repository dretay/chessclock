#!/usr/bin/env python3
"""Where the sea is, for routing the cruise ships between ports: apps/cruise/map/sea.bin.

    python3 tools/themegen/build_sea.py

The fleet map's region (tools/themegen/build_map.py's REGION: the Caribbean, the Gulf of Mexico,
Florida and the Bahamas) in cells of STEP degrees: a bit each, 1 where it's sea. A cell counts as land
if most of it is within about MARGIN degrees of land (Natural Earth's coastlines, assets/map/
ne_50m_land.geojson), so a route keeps a little offshore. apps/cruise/schedule.py finds the way
through it from port to port (around Florida, past Cuba) rather than across land.

The file: a first line "SEA lon0 lat0 step cols rows\\n", then the bits, row by row from the south,
each row padded to whole bytes (most significant bit first). Needs Pillow.
"""
import json, math, os
from PIL import Image, ImageDraw, ImageFilter

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LAND = os.path.join(REPO, "assets", "map", "ne_50m_land.geojson")
OUT = os.path.join(REPO, "apps", "cruise", "map", "sea.bin")
REGION = (-101.0, 5.0, -54.0, 36.5)            # lon0, lat0, lon1, lat1 (build_map.py's)
STEP = 0.125                                   # degrees a cell (about 7 nm)
SUB = 8                                        # each cell drawn as SUB x SUB pixels, to judge it closely
MARGIN = 0.03                                  # degrees kept clear of the coast (about 2 nm; more closes narrow channels: Cozumel, the Virgin Islands)


def main():
    lon0, lat0, lon1, lat1 = REGION
    cols, rows = round((lon1 - lon0) / STEP), round((lat1 - lat0) / STEP)
    W, H = cols * SUB, rows * SUB
    px = STEP / SUB                                                  # degrees a pixel
    img = Image.new("L", (W, H), 0)                                  # 255 where it's land; row 0 is the north
    d = ImageDraw.Draw(img)
    def xy(lon, lat): return ((lon - lon0) / px, (lat1 - lat) / px)
    for f in json.load(open(LAND))["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = poly[0]
            if max(p[0] for p in ring) < lon0 - 1 or min(p[0] for p in ring) > lon1 + 1: continue
            if max(p[1] for p in ring) < lat0 - 1 or min(p[1] for p in ring) > lat1 + 1: continue
            d.polygon([xy(*p) for p in ring], fill=255)
            for hole in poly[1:]: d.polygon([xy(*p) for p in hole], fill=0)
    grow = 2 * math.ceil(MARGIN / px) + 1
    img = img.filter(ImageFilter.MaxFilter(grow))                    # the margin
    small = img.resize((cols, rows), Image.BOX)                      # a cell: mostly land -> land (a harbour stays at sea)
    bits = bytearray()
    pix = small.load()
    for r in range(rows):                                            # from the south
        y = rows - 1 - r
        byte, n = 0, 0
        row = bytearray()
        for x in range(cols):
            byte = byte << 1 | (1 if pix[x, y] < 128 else 0); n += 1
            if n == 8: row.append(byte); byte, n = 0, 0
        if n: row.append(byte << (8 - n))
        bits += row
    with open(OUT, "wb") as f:
        f.write(("SEA %g %g %g %d %d\n" % (lon0, lat0, STEP, cols, rows)).encode()); f.write(bits)
    sea = sum(bin(b).count("1") for b in bits)
    print("sea: %s (%d x %d cells of %g degrees, %d%% sea, %d bytes)" % (os.path.relpath(OUT, REPO), cols, rows, STEP, 100 * sea // (cols * rows), os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
