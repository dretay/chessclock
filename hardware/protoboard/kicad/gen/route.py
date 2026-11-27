"""Specctra round trip for the autorouter (run with KiCad's Python).

  route.py export <board.kicad_pcb> <out.dsn>
  route.py import <board.kicad_pcb> <in.ses>
  route.py clean  <board.kicad_pcb> <drc.json>

import: replaces the tracks with the routed ones, then (after reloading the
board - the SES import leaves the Python wrappers stale) fixes vias the
import gave a netclass drill too big for their pad, removes dangling vias,
pours +3V3 into the free space on In2, refills all zones and saves in place.
"""
import sys

import pcbnew

MM = pcbnew.FromMM
PLANE_NETS = {"GND"}          # nets with a plane layer: a via with one track is fine

mode, pcb, path = sys.argv[1:4]
board = pcbnew.LoadBoard(pcb)

if mode == "clean":
    # remove the vias KiCad's DRC (JSON report at <path>) flags as dangling
    import json
    rep = json.load(open(path))
    spots = set()
    for v in rep.get("violations", []):
        for it in v.get("items", []):
            d = it.get("description", "")
            if v.get("type") == "via_dangling" or (
                    v.get("type") in ("clearance", "hole_clearance", "hole_to_hole", "shorting_items")
                    and d.startswith("Via [GND]")):   # stitching/plane vias are expendable
                spots.add((it["pos"]["x"], it["pos"]["y"]))
    n = 0
    for t in list(board.GetTracks()):
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            if any(abs(pcbnew.ToMM(p.x) - x) < 0.006 and abs(pcbnew.ToMM(p.y) - y) < 0.006 for x, y in spots):
                board.Remove(t)
                n += 1
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(pcb)
    print("removed %d dangling/conflicting vias" % n)
    sys.exit(0)

if mode == "export":
    # always export the unrouted board: no tracks, no post-route +3V3 pour
    import os
    for z in [board.GetArea(i) for i in range(board.GetAreaCount())]:
        if z.GetZoneName() in ("+3V3 pour", "GND pour top", "GND pour bottom", "+1V1 area"):
            board.Remove(z)
    if not os.environ.get("KEEP_TRACKS"):
        for t in list(board.GetTracks()):
            board.Remove(t)
    else:
        # drop the GND stitching vias (no track ends on them): the router would move them
        # around, and post re-adds them after routing
        ends = set()
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_TRACE_T:
                ends.add((t.GetStart().x, t.GetStart().y)); ends.add((t.GetEnd().x, t.GetEnd().y))
        for t in list(board.GetTracks()):
            if (t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND"
                    and (t.GetPosition().x, t.GetPosition().y) not in ends):
                board.Remove(t)
    ok = pcbnew.ExportSpecctraDSN(board, path)
    print("DSN export", "ok" if ok else "FAILED", path)
    sys.exit(0 if ok else 1)

# ---- phase 1: import
if mode == "post":
    pass
else:
  for t in list(board.GetTracks()):
    board.Remove(t)
  if not pcbnew.ImportSpecctraSES(board, path):
    raise SystemExit("SES import failed")
  board.Save(pcb)
if mode == "import":
    # the SES import leaves KiCad's SWIG layer unusable in this process: post-process in a new one
    import os
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "post", pcb, path])

# ---- phase 2 (mode "post", fresh process): clean up
tracks = list(board.GetTracks())

fixed = 0
for t in tracks:
    if t.Type() == pcbnew.PCB_VIA_T:
        d, dr = t.GetWidth(pcbnew.F_Cu), t.GetDrillValue()
        if d - dr < MM(0.25):                     # keep >= 0.125 mm annular ring
            t.SetDrill(max(MM(0.2), d - MM(0.25)))
            fixed += 1

removed = 0

names = [board.GetArea(i).GetZoneName() for i in range(board.GetAreaCount())]
if "+3V3 pour" not in names and "+3V3 plane" not in names:
    bb = board.GetBoardEdgesBoundingBox()
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.In2_Cu)
    z.SetNet(board.FindNet("+3V3"))
    z.SetLocalClearance(MM(0.3))
    z.SetMinThickness(MM(0.2))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    o = z.Outline()
    o.NewOutline()
    m = MM(0.5)
    for x, y in ((bb.GetLeft() + m, bb.GetTop() + m), (bb.GetRight() - m, bb.GetTop() + m),
                 (bb.GetRight() - m, bb.GetBottom() - m), (bb.GetLeft() + m, bb.GetBottom() - m)):
        o.Append(x, y)
    z.SetZoneName("+3V3 pour")
    board.Add(z)

# +1V1 area on In2 (priority over the +3V3 pour) from the core buck's inductor to under the
# SoC: the router's +1V1 escapes that end in a via, and gen/viafix.py's new ones, connect
# through it instead of needing a track all the way
if "+1V1 area" not in names and "+1V1 plane" not in names:
    v11 = board.FindNet("+1V1").GetNetCode()
    boxes = [fp.GetBoundingBox(False) for fp in board.GetFootprints()
             if fp.GetValue() == "F1C200s" or (fp.GetReference().startswith("L")
                                                and any(p.GetNetCode() == v11 for p in fp.Pads()))]
    if len(boxes) >= 2:
        bb = boxes[0]
        for x in boxes[1:]:
            bb.Merge(x)
        e = board.GetBoardEdgesBoundingBox()
        z = pcbnew.ZONE(board)
        z.SetLayer(pcbnew.In2_Cu)
        z.SetNet(board.FindNet("+1V1"))
        z.SetAssignedPriority(1)
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        o = z.Outline()
        o.NewOutline()
        x0, x1 = bb.GetLeft() - MM(1), bb.GetRight() + MM(1)
        y0, y1 = max(bb.GetTop() - MM(1), e.GetTop() + MM(0.5)), bb.GetBottom() + MM(1)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(int(x), int(y))
        z.SetZoneName("+1V1 area")
        board.Add(z)

# GND pours on the outer layers: pick up GND pads that had no room for their own via
# and stitch to the In1 plane through the GND vias the router placed
for layer, nm in ((pcbnew.F_Cu, "GND pour top"), (pcbnew.B_Cu, "GND pour bottom")):
    if nm in names:
        continue
    bb = board.GetBoardEdgesBoundingBox()
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(board.FindNet("GND"))
    z.SetLocalClearance(MM(0.25))
    z.SetMinThickness(MM(0.2))
    z.SetAssignedPriority(0)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    o = z.Outline()
    o.NewOutline()
    m = MM(0.5)
    for x, y in ((bb.GetLeft() + m, bb.GetTop() + m), (bb.GetRight() - m, bb.GetTop() + m),
                 (bb.GetRight() - m, bb.GetBottom() - m), (bb.GetLeft() + m, bb.GetBottom() - m)):
        o.Append(x, y)
    z.SetZoneName(nm)
    board.Add(z)

pcbnew.ZONE_FILLER(board).Fill(board.Zones())

# GND stitching: a via (to the In1 plane) on a grid wherever one fits; keep the ones that
# land in an outer GND pour, so pour islands around GND pads without a via get one
def grown(box, d):
    """A copy of box grown by d on each side (BOX2I.Inflate mutates in place, and on a
    temporary returned by GetBoundingBox() it returns a dangling reference)."""
    b = pcbnew.BOX2I(box.GetPosition(), box.GetSize())
    b.Inflate(d)
    return b


def stitch(pitch=1.27, dia=0.6, drill=0.3, clr=0.25, edge=1.0):
    gnd = board.FindNet("GND")
    bb = board.GetBoardEdgesBoundingBox()
    keep = [z for z in list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
            if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    pours = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "GND"
             and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)]
    items = []                                    # (bbox, shape-getter, net) for every copper item
    for fp in board.GetFootprints():
        for p in fp.Pads():
            items.append((grown(p.GetBoundingBox(), MM(1)), p, p.GetNetCode()))
    for t in board.GetTracks():
        items.append((grown(t.GetBoundingBox(), MM(1)), t, t.GetNetCode()))
    # zones are not obstacles: the refill clears around the new vias
    layers = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    if any(t.GetLayer() == pcbnew.In1_Cu for t in board.GetTracks()):
        layers.append(pcbnew.In1_Cu)              # In1 routing allowed (freerouting_in1.rules)
    placed, r = [], MM(dia / 2)
    y = bb.GetTop() + MM(edge)
    while y < bb.GetBottom() - MM(edge):
        x = bb.GetLeft() + MM(edge)
        while x < bb.GetRight() - MM(edge):
            pt = pcbnew.VECTOR2I(int(x), int(y))
            ok = not any(z.Outline().Collide(pcbnew.SHAPE_CIRCLE(pt, r), MM(0.05)) for z in keep)
            ok = ok and any(z.HitTestFilledArea(z.GetLayer(), pt) for z in pours)
            if ok:
                c = pcbnew.SHAPE_CIRCLE(pt, r)
                for box, it, net in items:
                    if not box.Contains(pt):        # box pre-inflated: Inflate() mutates in place
                        continue
                    g = MM(clr)
                    hit = False
                    for L in (layers if net != gnd.GetNetCode() else []):   # same net may touch
                        if it.IsOnLayer(L) and it.GetEffectiveShape(L).Collide(c, g):
                            hit = True; break
                    if it.Type() == pcbnew.PCB_VIA_T:      # any net: hole-to-hole and pad overlap
                        hit = hit or (it.GetPosition() - pt).EuclideanNorm() < MM(dia) + MM(0.3)
                    if it.Type() == pcbnew.PCB_PAD_T and it.HasHole():
                        hit = hit or it.GetEffectiveHoleShape().Collide(c, MM(0.3))
                    if hit:
                        ok = False; break
            if ok and all((pt - q).EuclideanNorm() >= MM(pitch * 1.9) for q in placed[-200:]):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pt); v.SetWidth(MM(dia)); v.SetDrill(MM(drill)); v.SetNet(gnd)
                board.Add(v); placed.append(pt)
                items.append((grown(v.GetBoundingBox(), MM(1)), v, gnd.GetNetCode()))
            x += MM(pitch)
        y += MM(pitch)
    return len(placed)

nstitch = stitch()
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
print("stitching vias: %d" % nstitch)
nvias = sum(1 for t in tracks if t.Type() == pcbnew.PCB_VIA_T) - removed
ntr = sum(1 for t in tracks if t.Type() != pcbnew.PCB_VIA_T)
board.Save(pcb)
print("imported: %d tracks, %d vias (%d drills fixed, %d dangling vias removed)" % (ntr, nvias, fixed, removed))
