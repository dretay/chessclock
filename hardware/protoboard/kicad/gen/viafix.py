"""Drop vias into a plane for unconnected pads/track ends (run with KiCad's Python).

  viafix.py <board.kicad_pcb> <drc.json> <net> <plane layer name>

For each unconnected item of <net> in the DRC report, looks for a via spot near
it (up to 2.5 mm away) where the plane on <plane layer> is filled, adds the via
and a straight track to it on the item's layer, checking clearance to every
other net on all copper layers. Refills and saves.
"""
import json
import sys

import pcbnew

MM = pcbnew.FromMM
pcb, rep, netname, plane_layer = sys.argv[1:5]
board = pcbnew.LoadBoard(pcb)
net = board.FindNet(netname)
PL = board.GetLayerID(plane_layer)
CLR = MM(0.15)
VIA_D, VIA_DR, TW = MM(0.6), MM(0.3), MM(0.2)
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]

planes = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetCode() == net.GetNetCode()
          and z.GetLayer() == PL]
keep = [z for z in list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
        if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
def grown(box, d):
    b = pcbnew.BOX2I(box.GetPosition(), box.GetSize())   # copy: Inflate() mutates / dangles on temporaries
    b.Inflate(d)
    return b


items = []                                   # (inflated bbox, item) for every copper item of another net
for fp in board.GetFootprints():
    for p in fp.Pads():
        if p.GetNetCode() != net.GetNetCode():
            items.append((grown(p.GetBoundingBox(), MM(1)), p))
for t in board.GetTracks():
    if t.GetNetCode() != net.GetNetCode():
        items.append((grown(t.GetBoundingBox(), MM(1)), t))


def clear(shape, layers, box):
    for bb, it in items:
        if not bb.Intersects(box):
            continue
        for L in layers:
            if it.IsOnLayer(L) and it.GetEffectiveShape(L).Collide(shape, CLR):
                return False
        if it.Type() == pcbnew.PCB_PAD_T and it.HasHole() and it.GetEffectiveHoleShape().Collide(shape, MM(0.25)):
            return False
    return True


def try_fix(pt, layer):
    best = None
    for r10 in range(4, 26, 2):                  # 0.4 .. 2.5 mm out
        r = r10 / 10
        for k in range(16):
            import math
            a = 2 * math.pi * k / 16
            v = pcbnew.VECTOR2I(int(pt.x + MM(r * math.cos(a))), int(pt.y + MM(r * math.sin(a))))
            if not any(z.HitTestFilledArea(PL, v, -int(VIA_D / 2)) for z in planes):
                continue
            c = pcbnew.SHAPE_CIRCLE(v, int(VIA_D / 2))
            if any(z.Outline().Collide(c, MM(0.05)) for z in keep):
                continue
            vb = pcbnew.BOX2I(v - pcbnew.VECTOR2I(int(VIA_D), int(VIA_D)), pcbnew.VECTOR2I(int(2 * VIA_D), int(2 * VIA_D)))
            if not clear(c, CU, vb):
                continue
            seg = pcbnew.SHAPE_SEGMENT(pt, v, TW)
            sb = pcbnew.BOX2I(pcbnew.VECTOR2I(min(pt.x, v.x) - MM(1), min(pt.y, v.y) - MM(1)),
                              pcbnew.VECTOR2I(abs(pt.x - v.x) + MM(2), abs(pt.y - v.y) + MM(2)))
            if not clear(seg, [layer], sb):
                continue
            best = v
            break
        if best:
            break
    if not best:
        return False
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(best); via.SetWidth(VIA_D); via.SetDrill(VIA_DR); via.SetNet(net)
    board.Add(via)
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(pt); tr.SetEnd(best); tr.SetWidth(TW); tr.SetLayer(layer); tr.SetNet(net)
    board.Add(tr)
    for o in (via, tr):                          # later fixes keep clear of these too? same net: no need
        pass
    return True


r = json.load(open(rep))
done, failed = 0, []
seen = set()
for u in r.get("unconnected_items", []):
    for it in u["items"]:
        d = it["description"]
        if "[%s]" % netname not in d:
            continue
        x, y = MM(it["pos"]["x"]), MM(it["pos"]["y"])
        key = (round(it["pos"]["x"], 2), round(it["pos"]["y"], 2))
        if key in seen:
            continue
        seen.add(key)
        pt = pcbnew.VECTOR2I(x, y)
        layer = pcbnew.B_Cu if " on B.Cu" in d else pcbnew.In2_Cu if "In2" in d else pcbnew.F_Cu
        if d.startswith("Track"):                # the report gives the track's position: use its nearest end
            for t in board.GetTracks():
                if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetCode() == net.GetNetCode() and t.HitTest(pt, MM(0.05)):
                    pt = min((t.GetStart(), t.GetEnd()), key=lambda e: (e - pt).EuclideanNorm())
                    layer = t.GetLayer()
                    break
        elif d.startswith("Zone"):
            continue
        ok = try_fix(pt, layer)
        if not ok and d.startswith("Pad"):
            # fine-pitch pad: step straight out from its footprint's centre first, then find a via
            fp = [f for f in board.GetFootprints() if any(p.GetPosition() == pt for p in f.Pads())]
            if fp:
                c0 = fp[0].GetPosition()
                dx, dy = pt.x - c0.x, pt.y - c0.y
                u = (1 if dx > 0 else -1, 0) if abs(dx) > abs(dy) else (0, 1 if dy > 0 else -1)
                for L in (0.8, 1.2, 1.6, 2.0):
                    q = pcbnew.VECTOR2I(int(pt.x + MM(L) * u[0]), int(pt.y + MM(L) * u[1]))
                    seg = pcbnew.SHAPE_SEGMENT(pt, q, MM(0.15))
                    sb_ = pcbnew.BOX2I(pcbnew.VECTOR2I(min(pt.x, q.x) - MM(1), min(pt.y, q.y) - MM(1)),
                                       pcbnew.VECTOR2I(abs(pt.x - q.x) + MM(2), abs(pt.y - q.y) + MM(2)))
                    if not clear(seg, [layer], sb_):
                        continue
                    if try_fix(q, layer):
                        st = pcbnew.PCB_TRACK(board)
                        st.SetStart(pt); st.SetEnd(q); st.SetWidth(MM(0.15)); st.SetLayer(layer); st.SetNet(net)
                        board.Add(st)
                        ok = True
                        break
        if ok:
            done += 1
        else:
            failed.append(d[:50])
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
board.Save(pcb)
print("vias added: %d, no room: %s" % (done, failed))
