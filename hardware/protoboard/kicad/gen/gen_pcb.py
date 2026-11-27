"""Build protoboard.kicad_pcb with KiCad's pcbnew API (run with KiCad's Python).

Nets and footprints come from the netlist KiCad exports from the schematic,
so the board is in parity with it. Key parts are pinned where DESIGN.md puts
them; every other part is packed, without overlaps, as close as possible to
the pads it connects to. Routing is left to the layout pass.

usage: <kicad python> gen_pcb.py <netlist.net> <out.kicad_pcb>
"""
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, findall  # noqa: E402

KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_FP = os.path.join(HERE, "..", "lib", "protoboard.pretty")

OX, OY = 100.0, 60.0          # board origin on the page (mm)
BW = float(os.environ.get("BOARD_W", 118.0))   # board size (panel 120.7 x 75.8, board centred sideways)
BH = float(os.environ.get("BOARD_H", 72.5))    # extra height goes to the bottom (prototyping) edge only:
                                               # the top (front) edge takes the LCD ribbon
SX = (BW - 110.0) / 2         # wider board: panel-relative parts (SoC, FPC, ribbon) shift right by SX
EY = BH - 70.0                # taller board: the prototyping half shifts down by EY
DX = 10.0 + SX                # board grew 10 mm each side vs the 90 mm spec: panel-relative parts shift by DX
SD_SIDE = os.environ.get("SD_SIDE") == "1"   # microSD on the right edge instead of the back edge
PLACE_GAP = float(os.environ.get("PLACE_GAP", 0.25))             # extra clearance around every auto-placed part (routing room)
CHIP_Y = 40.0 + EY            # bottom of the chip half
MM = pcbnew.FromMM

POWER = {"GND", "+5V", "+3V3", "+1V1", "+2V5", "+3V0", "ESP_5V", "ESP_3V3", "VBUS"}

# ---- fixed placements: ref-by-value/footprint matchers -> (x, y, rot) in board coords
# (resolved against the netlist below; see DESIGN.md "Board outline and the LCD ribbon")
G = 2.54


def V(x, y):
    return pcbnew.VECTOR2I(MM(OX + x), MM(OY + y))


def load_netlist(path):
    t = parse(open(path).read())[0]
    comps = []
    for c in findall(find(t, "components"), "comp"):
        ref = find(c, "ref")[1]
        fp = find(c, "footprint")
        sp = find(c, "sheetpath")
        props = {}
        for p in findall(c, "property"):
            v = find(p, "value")
            props[find(p, "name")[1]] = v[1] if v else ""
        fields = {}
        for f in findall(find(c, "fields") or [], "field"):
            fields[find(f, "name")[1]] = f[2] if len(f) > 2 and not isinstance(f[2], list) else ""
        comps.append(dict(ref=ref, value=find(c, "value")[1], footprint=fp[1] if fp else "", fields=fields,
                          sheetnames=find(sp, "names")[1], sheettstamps=find(sp, "tstamps")[1],
                          tstamp=find(c, "tstamps")[1] if find(c, "tstamps") else find(c, "tstamp")[1],
                          dnp="dnp" in props, props=props))
    nets = {}
    for n in findall(find(t, "nets"), "net"):
        name = find(n, "name")[1]
        for node in findall(n, "node"):
            nets[(find(node, "ref")[1], find(node, "pin")[1])] = name
    return comps, nets


def short(net):
    return net.split("/")[-1]


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    path = LOCAL_FP if lib == "protoboard" else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit("footprint not found: " + fpid)
    fp.SetFPIDAsString(fpid)
    return fp


def bbox_mm(fp, margin=0.25):
    fp.BuildCourtyardCaches()
    cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
    if cy.OutlineCount() > 0:
        bb = cy.BBox()
    else:
        bb = fp.GetBoundingBox(False)
    x0, y0 = pcbnew.ToMM(bb.GetX()) - OX, pcbnew.ToMM(bb.GetY()) - OY
    return (x0 - margin, y0 - margin, x0 + pcbnew.ToMM(bb.GetWidth()) + margin, y0 + pcbnew.ToMM(bb.GetHeight()) + margin)


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def main(netpath, outpath):
    comps, pinnet = load_netlist(netpath)
    by_ref = {c["ref"]: c for c in comps}

    def find_ref(pred):
        r = [c["ref"] for c in comps if pred(c)]
        return r

    def one(pred, what):
        r = find_ref(pred)
        if len(r) != 1:
            raise SystemExit("expected one %s, got %s" % (what, r))
        return r[0]

    val = lambda v: (lambda c: c["value"] == v)
    fixed = {}
    # The front (chip) half is laid out mirrored left-right (MX): seen from the front, the
    # panel's ribbon leaves 26 mm from its LEFT edge, which is the board's right side seen
    # from above with the front edge at the top. The SoC turns 90 degrees so its LCD pins
    # (left and bottom sides at 0 deg) face the connector below-right of it.
    MX = lambda x: BW - x
    SOC_ROT = int(os.environ.get("SOC_ROT", 180))
    fixed[one(val("F1C200s"), "SoC")] = (MX(44.0 + DX), 15.0, SOC_ROT)
    # the board lies flat in the stand's base, front (top) edge at the panel: the ribbon drops
    # onto that edge, lies over the chip half and runs into the connector ~30 mm back
    fpc = one(val("LCD 40P bottom-contact"), "FPC")
    fixed[fpc] = (MX(21.0 + DX), 30.5, 180)
    # USB-C (power + OTG/FEL) on the back edge, where the stand is powered from
    fixed[one(val("USB-C (power, OTG, FEL)"), "USB")] = (BW - 13.0, BH - 4.0, 0)
    if SD_SIDE:     # right edge, card in from the right, between the LCD connector and the USB-C
        fixed[one(val("microSD push-push"), "SD")] = (BW - 9.0, float(os.environ.get("SD_Y", 44.5)), 90)
    else:           # back edge, card in from the back (routes better: 5 vs 19 unconnected)
        fixed[one(val("microSD push-push"), "SD")] = (BW - 26.7, BH - 9.0, 0)
    fixed[one(val("ESP32-C3 SuperMini"), "ESP")] = (11.7, 27.6, 270)          # antenna at the left edge
    fixed[one(val("RESET"), "reset")] = (MX(77.0), 31.0, 0)
    fixed[one(val("FEL"), "fel")] = (MX(77.0), 22.5, 0)
    holes = sorted(find_ref(val("M3")))
    for r, (x, y) in zip(holes, [(3.5, 3.5), (BW - 3.5, 3.5), (3.5, BH - 3.5), (BW - 3.5, BH - 3.5)]):
        fixed[r] = (x, y, 0)

    # proto half: breakout row 1 (y=38.6), row 2 (y=42.6), rails at the bottom
    x = 5.0
    for v in ("I2C", "SPI0", "CONSOLE (UART0)", "UART2", "NEOPIXEL", "RCWL-0516"):
        r = one(val(v), v)
        n = sum(1 for (rr, _p) in pinnet if rr == r) if v != "RCWL-0516" else 5
        fixed[r] = (x, 42.0 + EY, 90)
        x += (n + 1) * G
    fixed[one(val("GPIO"), "gpio")] = (5.0, 46.0 + EY, 90)
    for i, v in enumerate(("RAIL 5V", "RAIL 3V3", "RAIL GND")):
        fixed[one(val(v), v)] = (9.5, BH - 7.8 + i * G, 0)
    fixed[one(val("5V IN"), "5V in")] = (BW - (25.2 if SD_SIDE else 41.0), BH - 5.4, 0)   # back edge: rails | 5V IN | (microSD) | USB-C

    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    board.SetLayerName(pcbnew.In1_Cu, "In1.Cu-GND")
    board.SetLayerName(pcbnew.In2_Cu, "In2.Cu-SIG-3V3")

    tb = board.GetTitleBlock()
    tb.SetTitle("F1C200s prototyping board")
    tb.SetRevision("0.1")
    tb.SetComment(0, "Generated from hardware/protoboard/DESIGN.md by kicad/gen/gen_pcb.py")
    tb.SetComment(1, "Placement only - route by hand / autorouter")

    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = MM(0.127)
    ds.m_MinClearance = MM(0.127)
    ds.m_ViasMinSize = MM(0.45)
    ds.m_MinThroughDrill = MM(0.2)
    ds.m_CopperEdgeClearance = MM(0.3)
    ds.m_HoleClearance = MM(0.2)

    # outline
    rect = pcbnew.PCB_SHAPE(board)
    rect.SetShape(pcbnew.SHAPE_T_RECT)
    rect.SetStart(V(0, 0))
    rect.SetEnd(V(BW, BH))
    rect.SetLayer(pcbnew.Edge_Cuts)
    rect.SetWidth(MM(0.1))
    board.Add(rect)

    # nets
    netobj = {}
    for name in sorted(set(pinnet.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netobj[name] = ni

    # footprints
    fps = {}
    for c in comps:
        if c["ref"].startswith("#") or not c["footprint"]:
            continue
        fp = load_fp(c["footprint"])
        fp.SetReference(c["ref"])
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["sheettstamps"] + c["tstamp"]))
        fp.SetSheetname(c["props"].get("Sheetname", ""))
        fp.SetSheetfile(c["props"].get("Sheetfile", ""))
        for k, v in c["fields"].items():
            if k not in ("Footprint", "Reference", "Value"):
                fp.SetField(k, v)
                fld = fp.GetField(k)
                if fld:
                    fld.SetVisible(False)
                    fld.SetLayer(pcbnew.F_Fab)
        attrs = fp.GetAttributes()
        if "exclude_from_bom" in c["props"]:
            attrs |= pcbnew.FP_EXCLUDE_FROM_BOM
        else:
            attrs &= ~pcbnew.FP_EXCLUDE_FROM_BOM
        fp.SetAttributes(attrs)
        if c["dnp"]:
            fp.SetDNP(True)
        if c["ref"][0] in "RCL" and not c["ref"].startswith("RAIL"):
            fp.Reference().SetLayer(pcbnew.F_Fab)     # dense passives: designators on the assembly drawing
        else:
            fp.Reference().SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
            fp.Reference().SetTextThickness(MM(0.12))
        for pad in fp.Pads():
            n = pinnet.get((c["ref"], pad.GetNumber()))
            if n:
                pad.SetNet(netobj[n])
        board.Add(fp)
        fps[c["ref"]] = fp

    # protogrid (board-only)
    GRID_C = 38 if SD_SIDE else 31          # microSD on the back edge takes the grid's right end
    grid = load_fp("protoboard:Protogrid_%dx5_P2.54mm" % GRID_C)
    grid.SetReference("PROTO1")
    grid.SetValue("%d x 5 grid" % GRID_C)
    grid.Reference().SetVisible(False)
    board.Add(grid)
    grid.SetPosition(V(4.0, 49.6 + EY))

    placed = [bbox_mm(grid, 0.1)]
    # keep-outs: board margin strips and mounting holes, the ESP antenna
    keep = [(-5, -5, BW + 5, 0.3), (-5, BH - 0.3, BW + 5, BH + 5), (-5, -5, 0.3, BH + 5), (BW - 0.3, -5, BW + 5, BH + 5)]

    for ref, (x, y, rot) in fixed.items():
        fp = fps[ref]
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(V(x, y))
        placed.append(bbox_mm(fp, 0.1))

    # ------------------------------------------------------------ silk labels
    SZ = 0.8

    def text_box(t, x, y, size=SZ, angle=0, just="c"):
        w, h = len(t) * size * 0.85 + 0.2, size * 1.45
        if angle in (90, 270):
            w, h = h, w
        x0 = x - w / 2 if just == "c" else (x if just == "l" else x - w)
        return (x0, y - h / 2, x0 + w, y + h / 2)

    def silk(t, x, y, size=SZ, angle=0, just="c", layer=pcbnew.F_SilkS, reserve=True):
        tx = pcbnew.PCB_TEXT(board)
        tx.SetText(t)
        tx.SetPosition(V(x, y))
        tx.SetLayer(layer)
        tx.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        tx.SetTextThickness(MM(max(0.1, size * 0.15)))
        tx.SetTextAngleDegrees(angle)
        if just == "l":
            tx.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        elif just == "r":
            tx.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
        if layer == pcbnew.B_SilkS:
            tx.SetMirrored(True)
        board.Add(tx)
        if reserve:
            placed.append(text_box(t, x, y, size, angle, just))

    ABBR = {"GND": "GND", "+3V3": "3V3", "+5V": "5V", "I2C0_SDA": "SDA", "I2C0_SCL": "SCL",
            "SPI0_CLK": "SCK", "SPI0_MOSI": "MO", "SPI0_MISO": "MI", "SPI0_CS2": "CS",
            "UART0_RX": "RX", "UART0_TX": "TX", "UART2_TX_BRK": "TX", "UART2_RX_BRK": "RX",
            "NEO_DOUT": "DIN", "GPIO_PE3": "PE3", "LRADC0": "ADC", "EXP_P07": "X07"}
    for i in range(8):
        ABBR["EXP_P1%d" % i] = "X1%d" % i
    RCWL = {"1": "3Vo", "2": "GND", "3": "OUT", "4": "VIN", "5": "CDS"}

    def pads_of(ref):
        out = []
        for pad in fps[ref].Pads():
            p = pad.GetPosition()
            out.append((pad.GetNumber(), pcbnew.ToMM(p.x) - OX, pcbnew.ToMM(p.y) - OY,
                        short(pinnet.get((ref, pad.GetNumber()), ""))))
        return out

    TITLES = {"I2C": "I2C", "SPI0": "SPI0", "CONSOLE (UART0)": "UART0", "UART2": "UART2",
              "NEOPIXEL": "NEO", "RCWL-0516": "RCWL", "GPIO": "GPIO"}
    for v, title in TITLES.items():
        r = one(val(v), v)
        ps = pads_of(r)
        below = v == "GPIO"
        for num, x, y, net in ps:
            lab = RCWL[num] if v == "RCWL-0516" else ABBR.get(net, net[-3:])
            silk(lab, x, y + 2.0 if below else y - 2.0, SZ)
        x0 = min(p[1] for p in ps)
        silk(title, x0 - 2.54, ps[0][2], SZ, 90)
    for i, s_ in enumerate(("5V", "3V3", "GND")):
        silk(s_, 6.4, BH - 7.8 + i * G, SZ, reserve=False)

    # purpose labels on fixed parts
    def label_fixed(v, t, dx, dy, angle=0):
        r = one(val(v), v)
        bb = bbox_mm(fps[r], 0)
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        silk(t, cx + dx, cy + dy, SZ, angle)
    label_fixed("RESET", "RESET", 0, 0)            # inside the button outline, under the cap
    label_fixed("FEL", "FEL", 0, 0)
    r5 = one(val("5V IN"), "5V in")
    for num, x, y, net in pads_of(r5):
        silk("+" if net == "VIN_EXT" else "-", x, y - 2.2, 1.0)
    bb5 = bbox_mm(fps[r5], 0)
    silk("5V IN", (bb5[0] + bb5[2]) / 2, bb5[1] - 0.8, SZ)
    # the silk titles name these connectors: designators go to the assembly drawing
    for v in list(TITLES) + ["RAIL 5V", "RAIL 3V3", "RAIL GND", "5V IN"]:
        for r in find_ref(val(v)):
            fps[r].Reference().SetLayer(pcbnew.F_Fab)
    label_fixed("LCD 40P bottom-contact", "LCD  (pin 1 right)", 0, 0)
    label_fixed("USB-C (power, OTG, FEL)", "USB", 0, -6.5)

    # purpose labels for auto-placed parts: value -> (text, side)
    PURPOSE = {"Speaker L": ("SPK L +-", "b"), "Speaker R": ("SPK R +-", "b"), "MIC": ("MIC + G", "b"),
               "green": ("PWR", "r"), "status 1": ("LED1", "r"), "status 2": ("LED2", "r"),
               "UART2 TX: ESP|BRK": ("TX2 ESP|BRK", "b"), "UART2 RX: ESP|BRK": ("RX2 ESP|BRK", "b"),
               "NeoPixel <- SPI0 MOSI": ("NEO<MOSI", "b")}
    TPN = {"+1V1": "1V1", "+2V5": "2V5", "+3V0": "3V0", "USB_DP": "D+", "USB_DM": "D-", "SPI1_CS": "CS1",
           "SPI1_MOSI": "MO1", "SPI1_CLK": "CK1", "SPI1_MISO": "MI1", "ESP_GPIO9": "IO9",
           "ESP_HANDSHAKE": "HS", "ESP_DATAREADY": "DR", "ESP_5V": "E5V", "ESP_3V3": "E3V3",
           "ESP_EN (bodge to module EN)": "EN>wire"}
    purpose = {}
    for c in comps:
        if c["ref"] in fps and c["value"] in PURPOSE:
            purpose[c["ref"]] = PURPOSE[c["value"]]
        elif c["ref"].startswith("TP") and c["value"] in TPN:
            purpose[c["ref"]] = (TPN[c["value"]], "r")
            fps[c["ref"]].Reference().SetLayer(pcbnew.F_Fab)

    for r in purpose:                       # the purpose label replaces the designator on silk
        fps[r].Reference().SetLayer(pcbnew.F_Fab)

    def grow(bb, ref):
        if ref not in purpose:
            return bb
        t, side = purpose[ref]
        w, h = len(t) * SZ * 0.85 + 0.4, SZ * 1.45 + 0.1
        if side == "b":
            return (min(bb[0], (bb[0] + bb[2]) / 2 - w / 2), bb[1], max(bb[2], (bb[0] + bb[2]) / 2 + w / 2), bb[3] + h)
        return (bb[0], min(bb[1], (bb[1] + bb[3]) / 2 - h / 2), bb[2] + w, max(bb[3], (bb[1] + bb[3]) / 2 + h / 2))

    def place_purpose(ref):
        if ref not in purpose:
            return
        t, side = purpose[ref]
        bb = bbox_mm(fps[ref], 0)
        if fps[ref].IsFlipped():
            w = len(t) * SZ * 0.85
            silk(t, bb[2] + 0.2 + w / 2, (bb[1] + bb[3]) / 2, SZ, layer=pcbnew.B_SilkS, reserve=False)
            return
        if side == "b":
            silk(t, (bb[0] + bb[2]) / 2, bb[3] + SZ * 0.75 + 0.05, SZ, reserve=False)
        else:
            silk(t, bb[2] + 0.2, (bb[1] + bb[3]) / 2, SZ, just="l", reserve=False)

    # antenna keep-out (no copper, all layers) at the left edge
    # antenna keep-out: beyond the last pin pair and between the pin rows at the
    # antenna end - the pins themselves must stay reachable
    esp = fps[one(val("ESP32-C3 SuperMini"), "ESP")]
    ep = [(pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY) for p in esp.Pads()]
    ex = min(p[0] for p in ep)
    ey0, ey1 = min(p[1] for p in ep), max(p[1] for p in ep)
    ant = (0.0, ey0 + 1.4, ex + 4.0, ey1 - 1.4)
    ra = pcbnew.ZONE(board)
    ra.SetIsRuleArea(True)
    ra.SetDoNotAllowTracks(True)
    ra.SetDoNotAllowVias(True)
    ra.SetDoNotAllowZoneFills(True)
    ra.SetDoNotAllowPads(False)
    ra.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET.AllCuMask(4) if hasattr(pcbnew.LSET, "AllCuMask") else pcbnew.LSET.AllCuMask()
    ra.SetLayerSet(ls)
    ol = ra.Outline()
    ol.NewOutline()
    for px, py in ((ant[0], ant[1]), (ant[2], ant[1]), (ant[2], ant[3]), (ant[0], ant[3])):
        ol.Append(MM(OX + px), MM(OY + py))
    ra.SetZoneName("ESP antenna keep-out")
    board.Add(ra)

    # ------------------------------------------------------------ routing reservations
    # escape ring around the 0.4 mm QFN: pins fan out on F.Cu before dropping to vias
    soc = fps[one(val("F1C200s"), "SoC")]
    sb = bbox_mm(soc, 0)
    ring = float(os.environ.get("QFN_RING", 2.0))
    placed.append((sb[0] - ring, sb[1] - ring, sb[2] + ring, sb[3] + ring))
    # band behind the LCD connector's pad row: all 22 LCD lines arrive from there
    lcd = fps[fpc]
    lp = [(pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY) for p in lcd.Pads() if p.GetNumber() != "MP"]
    lx0, lx1 = min(p[0] for p in lp), max(p[0] for p in lp)
    ly = max(p[1] for p in lp)
    placed.append((lx0 - 1.0, ly - 0.5, lx1 + 1.0, ly + 3.0))
    # LCD fan-out: the 22 lines run from the SoC's bottom and right pins down-right to the
    # connector, and HSYNC/VSYNC/DE/CLK (far end of the connector) cross the RGB lines on
    # vias - keep this area free of parts
    if SOC_ROT == 90:
        fan = (sb[2] + ring, sb[1] + 4.0, lx0 + 5.0, ly - 0.5)
    elif SOC_ROT == 180:       # LCD pins on the right and top sides
        fan = (sb[2] + ring, sb[1] - ring, lx0 + 5.0, ly - 0.5)
    else:                      # 0: LCD pins on the left and bottom sides, the lines pass under the chip
        fan = (sb[0] - ring, sb[3] + ring, lx0 + 5.0, ly - 0.5)
    placed.append(fan)
    # the ribbon lies on the board face from the front edge to the connector (DESIGN.md): its
    # wide section over the first ~19 mm, its tail down to the connector. Only low SMD parts
    # there (+2.5 mm margin: the ribbon size is measured by hand, not from a drawing)
    RM = 2.5
    RIBBON = [(MX(DX + 57.6 + RM), 0.0, MX(DX + 10.6 - RM), 19.0 + RM), (lx0 - 1.0 - RM, 0.0, lx1 + 1.0 + RM, ly)]

    # ------------------------------------------------------------ auto placement
    def pad_xy(fp, pad):
        p = pad.GetPosition()
        return pcbnew.ToMM(p.x) - OX, pcbnew.ToMM(p.y) - OY

    import json
    decl = json.load(open(os.path.join(HERE, ".cache", "order.json")))
    order = [r for r in decl if r in fps and r not in fixed]
    is_anchor = lambda r: r[0] == "U" or r.startswith("M") or r.startswith("J")
    # anchors (ICs, connectors) first, in netlist order, then the rest
    prio = ["soc.kicad_sch", "display.kicad_sch", "power.kicad_sch", "storage.kicad_sch", "wifi.kicad_sch",
            "audio.kicad_sch", "io.kicad_sch"]
    sk = lambda r: prio.index(by_ref[r]["props"].get("Sheetfile"))
    # the SoC's decoupling caps right after the anchors, before other passives take the
    # space next to its power pins
    pwr_only = lambda r: all(short(pinnet.get((r, pd.GetNumber()), "GND")) in POWER for pd in fps[r].Pads())
    soc_dec = [r for r in order if not is_anchor(r) and r[0] == "C" and pwr_only(r)
               and by_ref[r]["props"].get("Sheetfile") == "soc.kicad_sch"]
    # ...but the crystal and its load caps first: their traces matter more
    xtal_nets = {pinnet.get((r, pd.GetNumber())) for r in order if r[0] == "Y" for pd in fps[r].Pads()} - {None}
    xtal = [r for r in order if r[0] == "Y"] + [r for r in order if r[0] == "C" and not is_anchor(r) and any(
        pinnet.get((r, pd.GetNumber())) in xtal_nets and short(pinnet.get((r, pd.GetNumber()))) not in POWER
        for pd in fps[r].Pads())]
    soc_dec = [r for r in soc_dec if r not in xtal]
    order = ([r for r in order if is_anchor(r)] + xtal + soc_dec
             + sorted([r for r in order if not is_anchor(r) and r not in soc_dec and r not in xtal], key=sk))
    done = set(fixed)

    # nominal spots for free anchors (board coords) - the packer starts here
    hint = {}

    def hint_val(v, xy):
        if xy:      # chip-half hints follow the SoC (mirrored), proto-half ones follow the bottom edge
            xy = (MX(xy[0] + SX), xy[1]) if xy[1] < 40.0 else (xy[0] + 2 * SX, xy[1] + EY)
        for r in find_ref(val(v)):
            hint[r] = xy
    hint_val("SY8089AAAC", None)
    bucks = sorted(find_ref(val("SY8089AAAC")), key=lambda s: int(s[1:]))
    # +1V1, +2V5, +3V3 bucks along the front edge (unmirrored x), the core supply nearest the SoC
    bx = [float(v) for v in os.environ.get("BUCK_X", "14,26,38").split(",")]
    for r, x in zip(bucks, bx):
        hint[r] = (MX(x), 4.5)
    hint_val("LN6206P302", (45.0, 10.0))     # clear of the LCD fan-out
    hint_val("PT4103", (18.0, 24.0))
    hint_val("NS2009", (26.0, 23.0))
    hint_val("USBLC6-2SC6", (97.0, 57.0))  # just inside the back-edge USB-C
    hint_val("AO3401A", (93.0, 58.5))
    hint_val("TCA9535PWR", (62.0, 29.0))
    hint_val("74LVC244", (68.0, 8.0))
    hint_val("TPS22917", (86.0, 37.5))
    hint_val("W25Q128JVS (optional)", (63.0, 19.0))
    hint_val("PAM8403", (52.0, 30.0))
    hint_val("74AHCT1G125", (75.0, 46.0))
    # speakers / mic: no hint - they land next to the PAM8403 pads they connect to
    # NeoPixel bulk cap (+5V/GND only): falls back to the last io-sheet anchor, the NeoPixel buffer

    sheet_last_anchor = {}
    rail_turn = {}

    def target_for(ref):
        if ref in hint and hint[ref]:
            return hint[ref]
        pts = []
        fp = fps[ref]
        for pad in fp.Pads():
            n = pinnet.get((ref, pad.GetNumber()))
            if not n or short(n) in POWER or n.startswith("unconnected"):
                continue
            for (r2, p2), n2 in pinnet.items():
                if n2 == n and r2 != ref and r2 in done and r2 in fps:
                    for pd in fps[r2].Pads():
                        if pd.GetNumber() == p2:
                            pts.append(pad_xy(fps[r2], pd))
        if pts:
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        sh = by_ref[ref]["sheetnames"]
        # power-only part (decoupling cap): next to a pin of the same rail on the IC declared
        # just before it on this sheet; caps on one rail take that IC's rail pins in turn
        rails = {short(pinnet.get((ref, pd.GetNumber()), "")) for pd in fp.Pads()} - {"GND", ""}
        if rails:
            i = decl.index(ref)
            ic = next((r for r in reversed(decl[:i]) if r.startswith("U") and r in done
                       and by_ref[r]["sheetnames"] == sh), None)
            if ic:
                rail = sorted(rails)[0]
                rp = [pad_xy(fps[ic], pd) for pd in fps[ic].Pads()
                      if short(pinnet.get((ic, pd.GetNumber()), "")) == rail]
                if rp:
                    k = rail_turn.get((ic, rail), 0)
                    rail_turn[(ic, rail)] = k + 1
                    return rp[k % len(rp)]
        if sh in sheet_last_anchor:
            return sheet_last_anchor[sh]
        return (45.0, 20.0)

    def free(bb, chip_only, occ=None, tall=False):
        if tall and any(overlaps(bb, rz) for rz in RIBBON):
            return False
        if bb[0] < 0.3 or bb[1] < 0.3 or bb[2] > BW - 0.3 or bb[3] > BH - 0.3:
            return False
        if chip_only and bb[3] > CHIP_Y + 0.6:
            return False
        if overlaps(bb, ant):
            return False
        return not any(overlaps(bb, o) for o in (placed if occ is None else occ))

    # test points go on the bottom (flat pads, nothing tall facing the LCD):
    # there they only have to clear through-hole parts and each other
    def has_tht(fp):
        return any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in fp.Pads())
    placed_bot = [bbox_mm(grid, 0.1)] + [bbox_mm(fps[r], 0.1) for r in fixed if has_tht(fps[r])]
    for r in [r for r in order if r.startswith("TP")]:
        fps[r].Flip(fps[r].GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)

    unplaced = []
    for ref in order:
        fp = fps[ref]
        bottom = ref.startswith("TP")
        tx, ty = target_for(ref)
        chip_only = by_ref[ref]["props"].get("Sheetfile") in ("soc.kicad_sch", "display.kicad_sch", "storage.kicad_sch") and not bottom
        occ = placed_bot if bottom else placed
        tall = not bottom and (has_tht(fp) or ref.startswith("J") or ref.startswith("SW"))
        best = None
        rel = {}
        for rot in (0, 90):
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(V(0, 0))
            rel[rot] = grow(bbox_mm(fp, PLACE_GAP), ref)
        steps = 0
        for chip_only in ((chip_only, False) if chip_only else (False,)):   # chip half full: anywhere
            r = 0.0
            while best is None and r < (45 if chip_only else 120):
                n = max(1, int(2 * math.pi * r / 0.25))
                for i in range(n):
                    ang = 2 * math.pi * i / n
                    cx = round((tx + r * math.cos(ang)) * 4) / 4
                    cy = round((ty + r * math.sin(ang)) * 4) / 4
                    for rot in (0, 90):
                        b0 = rel[rot]
                        bb = (b0[0] + cx, b0[1] + cy, b0[2] + cx, b0[3] + cy)
                        if free(bb, chip_only, occ, tall):
                            best = (r, rot, cx, cy)
                            break
                    if best:
                        break
                r += 0.25
        if best is None:
            unplaced.append(ref)
            fp.SetPosition(V(BW + 10, 10 + len(unplaced) * 4))
            continue
        _, rot, cx, cy = best
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(V(cx, cy))
        occ.append(grow(bbox_mm(fp, PLACE_GAP), ref))
        if not bottom and has_tht(fp):
            placed_bot.append(bbox_mm(fp, 0.1))
        place_purpose(ref)
        done.add(ref)
        sheet_last_anchor[by_ref[ref]["sheetnames"]] = (cx, cy) if is_anchor(ref) else sheet_last_anchor.get(by_ref[ref]["sheetnames"], (cx, cy))

    # planes: GND on In1, +3V3 on In2, GND pour on both outer layers
    def plane(layer, net, prio=0):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(netobj[net])
        z.SetAssignedPriority(prio)
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        o = z.Outline()
        o.NewOutline()
        for px, py in ((0.5, 0.5), (BW - 0.5, 0.5), (BW - 0.5, BH - 0.5), (0.5, BH - 0.5)):
            o.Append(MM(OX + px), MM(OY + py))
        z.SetZoneName("%s plane" % net)
        board.Add(z)
    plane(pcbnew.In1_Cu, "GND")
    # In1 stays a solid GND plane: no tracks there (vias and the fill are fine).
    # Exported to the autorouter as a wire keep-out.
    ko = pcbnew.ZONE(board)
    ko.SetIsRuleArea(True)
    ko.SetDoNotAllowTracks(True)
    ko.SetDoNotAllowVias(False)
    ko.SetDoNotAllowZoneFills(False)
    ko.SetDoNotAllowPads(False)
    ko.SetDoNotAllowFootprints(False)
    ko.SetLayer(pcbnew.In1_Cu)
    o = ko.Outline()
    o.NewOutline()
    for px, py in ((0.2, 0.2), (BW - 0.2, 0.2), (BW - 0.2, BH - 0.2), (0.2, BH - 0.2)):
        o.Append(MM(OX + px), MM(OY + py))
    ko.SetZoneName("In1 GND plane: no tracks")
    board.Add(ko)
    if os.environ.get("PLANE_3V3"):
        plane(pcbnew.In2_Cu, "+3V3")          # variant A: solid +3V3 plane, signals on F/B only
    if os.environ.get("PLANE_1V1") == "1":
        # +1V1 (core) area on In2 from its buck's inductor to under the SoC: the router reaches it
        # with a via per pin, like the GND plane. Priority over the post-route +3V3 pour.
        lv = [fps[r] for r in fps if r.startswith("L") and any(pinnet.get((r, p.GetNumber())) == "+1V1" for p in fps[r].Pads())]
        xs = [bbox_mm(f, 0) for f in lv] + [sb]
        z = pcbnew.ZONE(board)
        z.SetLayer(pcbnew.In2_Cu)
        z.SetNet(netobj["+1V1"])
        z.SetAssignedPriority(1)
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        x0, x1 = min(b[0] for b in xs) - 1.0, max(b[2] for b in xs) + 1.0
        y0, y1 = 0.5, sb[3] + 1.0
        o = z.Outline()
        o.NewOutline()
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(MM(OX + px), MM(OY + py))
        z.SetZoneName("+1V1 plane")
        board.Add(z)
    # 0.5 mm no-track strip inside the board edge (the router otherwise hugs the edge)
    for ex0, ey0, ex1, ey1 in ((0, 0, BW, 0.5), (0, BH - 0.5, BW, BH), (0, 0, 0.5, BH), (BW - 0.5, 0, BW, BH)):
        ek = pcbnew.ZONE(board)
        ek.SetIsRuleArea(True)
        ek.SetDoNotAllowTracks(True)
        ek.SetDoNotAllowVias(True)
        ek.SetDoNotAllowZoneFills(False)
        ek.SetDoNotAllowPads(False)
        ek.SetDoNotAllowFootprints(False)
        ek.SetLayerSet(pcbnew.LSET.AllCuMask())
        eo = ek.Outline()
        eo.NewOutline()
        for px, py in ((ex0, ey0), (ex1, ey0), (ex1, ey1), (ex0, ey1)):
            eo.Append(MM(OX + px), MM(OY + py))
        ek.SetZoneName("edge keep-out")
        board.Add(ek)
    # otherwise In2 carries signals and route.py pours +3V3 into what is left after routing

    silk("F1C200s protoboard v0.1", 45, BH - 1.0, 0.8, layer=pcbnew.B_SilkS, reserve=False)

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(outpath)

    print("footprints:", len(fps), "fixed:", len(fixed), "auto:", len(done) - len(fixed))
    if unplaced:
        print("UNPLACED (parked right of the board):", " ".join(unplaced))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
