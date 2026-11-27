"""Write lib/protoboard.kicad_sym and lib/protoboard.pretty/ (custom parts)."""
import json
import os

from sexp import q, fmt

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
G = 2.54


def rect_symbol(name, ref, value, footprint, left, right, top=(), bottom=(), descr="",
                datasheet="~", width=None):
    """left/right/top/bottom: lists of (number, name, type) or None for a gap."""
    rows = max(len(left), len(right))
    h = (rows + 1) * G
    if width is None:
        longest = max([len(p[1]) for p in left + right if p] + [4])
        width = max(10.16, round((longest * 1.27 * 2 + 5) / G) * G)
    w = width
    x0, x1 = -w / 2, w / 2
    y0 = (rows - 1) * G / 2 + G   # top edge
    y0 = round(y0 / 1.27) * 1.27
    yb = y0 - h
    if top or bottom:
        n = max(len(top), len(bottom))
        w = max(w, (n + 1) * G)
        x0, x1 = -w / 2, w / 2
    L = 2.54
    out = []
    out.append('\t(symbol %s (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)' % q(name))
    out.append('\t\t(property "Reference" %s (at %s %s 0) (effects (font (size 1.27 1.27)) (justify left)))' % (q(ref), fmt(x0), fmt(y0 + 1.27)))
    out.append('\t\t(property "Value" %s (at %s %s 0) (effects (font (size 1.27 1.27)) (justify left)))' % (q(value), fmt(x0), fmt(yb - 1.27)))
    out.append('\t\t(property "Footprint" %s (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))' % q(footprint))
    out.append('\t\t(property "Datasheet" %s (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))' % q(datasheet))
    out.append('\t\t(property "Description" %s (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))' % q(descr))
    out.append('\t\t(symbol %s (rectangle (start %s %s) (end %s %s) (stroke (width 0.254) (type default)) (fill (type background))))'
               % (q(name + "_0_1"), fmt(x0), fmt(y0), fmt(x1), fmt(yb)))
    pins = []

    def pin(num, pname, ptype, x, y, ang):
        hide = ""
        pins.append('\t\t\t(pin %s line (at %s %s %d) (length %s)%s (name %s (effects (font (size 1.016 1.016)))) (number %s (effects (font (size 1.016 1.016)))))'
                    % (ptype, fmt(x), fmt(y), ang, fmt(L), hide, q(pname), q(num)))

    for i, p in enumerate(left):
        if p:
            pin(p[0], p[1], p[2], x0 - L, y0 - G * (i + 1), 0)
    for i, p in enumerate(right):
        if p:
            pin(p[0], p[1], p[2], x1 + L, y0 - G * (i + 1), 180)
    n = len(top)
    for i, p in enumerate(top):
        if p:
            pin(p[0], p[1], p[2], (i - (n - 1) / 2) * G, y0 + L, 270)
    n = len(bottom)
    for i, p in enumerate(bottom):
        if p:
            pin(p[0], p[1], p[2], (i - (n - 1) / 2) * G, yb - L, 90)
    out.append('\t\t(symbol %s\n%s\n\t\t)' % (q(name + "_1_1"), "\n".join(pins)))
    out.append('\t)')
    return "\n".join(out)


def f1c200s():
    pins = {int(k): v for k, v in json.load(open(os.path.join(HERE, "f1c_pins.json"))).items()}
    pwr_names = {"HPVCC", "VCC-IO", "VDD-CORE", "VCC-DRAM", "UVCC", "TV_VCC", "AVCC", "GND", "AGND", "TVGND"}

    def t(nm):
        if nm in pwr_names:
            return "power_in"
        if nm.startswith("P") and nm[1] in "ACDEF" and nm[2].isdigit():
            return "bidirectional"
        if nm in ("HPL", "HPR", "HPCOM", "TVOUT", "HOSCO"):
            return "output"
        if nm in ("USB-DM", "USB-DP"):
            return "bidirectional"
        if nm in ("SVREF", "VRA1", "VRA2", "TV_VRN", "TV_VRP", "HPCOMFB"):
            return "passive"
        return "input"

    by = {}
    for n, nm in pins.items():
        by.setdefault(nm.split("/")[0], []).append(n)

    def port(prefix):
        items = [(n, nm) for n, nm in pins.items() if nm.startswith(prefix) and nm[len(prefix)].isdigit()]
        items.sort(key=lambda x: int(x[1].split("/")[0][2:]))
        return [(str(n), nm, t(nm)) for n, nm in items]

    right = port("PD") + [None] + port("PE")
    right2 = port("PA") + [None] + port("PC") + [None] + port("PF")
    order = ["VDD-CORE", "VCC-DRAM", "SVREF", "VCC-IO", "UVCC", "HPVCC", "TV_VCC", "AVCC", "VRA1", "VRA2",
             None, "RESET", "HOSCI", "HOSCO", None, "USB-DP", "USB-DM", None, "LRADC0", "MICIN", "LINEIN",
             "FMINL", "FMINR", "HPL", "HPR", "HPCOM", "HPCOMFB", None, "TVOUT", "TVIN0", "TVIN1", "TV_VRN", "TV_VRP",
             None, "GND", "AGND", "TVGND"]
    left = []
    for nm in order:
        if nm is None:
            left.append(None)
            continue
        for n in sorted(by[nm]):
            left.append((str(n), pins[n], t(pins[n])))
    left += [None] + right2
    used = {int(p[0]) for p in left + right if p}
    assert used == set(range(1, 90)), set(range(1, 90)) - used
    return rect_symbol("F1C200s", "U", "F1C200s",
                       "protoboard:F1C200s_QFN-88-1EP_10x10mm_P0.4mm_EP6.74x6.74mm_ThermalVias",
                       left, right, descr="Allwinner F1C200s ARM926EJ-S SoC, 64 MB DDR, QFN-88 10x10 0.4 mm (pinout = F1C100s, from Lichee Pi Nano schematic)",
                       width=45.72)


def simple_syms():
    S = []
    S.append(rect_symbol("SY8089", "U", "SY8089AAAC", "Package_TO_SOT_SMD:SOT-23-5",
                         [("4", "IN", "power_in"), ("1", "EN", "input")],
                         [("3", "LX", "passive"), ("5", "FB", "input")],
                         bottom=[("2", "GND", "power_in")],
                         descr="Silergy SY8089 2 A 1.5 MHz synchronous buck, 0.6 V reference, SOT-23-5",
                         datasheet="https://www.silergy.com/download/downloadFile?id=4652&type=product&ftype=note"))
    S.append(rect_symbol("PT4103", "U", "PT4103", "Package_TO_SOT_SMD:SOT-23-6",
                         [("6", "IN", "power_in"), ("4", "EN", "input")],
                         [("1", "SW", "passive"), ("5", "OV", "input"), ("3", "FB", "input")],
                         bottom=[("2", "GND", "power_in")],
                         descr="PowTech PT4103 boost white-LED driver, 104 mV FB, SOT-23-6 (pinout from Lichee Pi Nano)"))
    S.append(rect_symbol("NS2009", "U", "NS2009", "Package_SO:MSOP-10_3x3mm_P0.5mm",
                         [("2", "XP", "passive"), ("3", "YP", "passive"), ("4", "XN", "passive"), ("5", "YN", "passive"), None, ("8", "A0", "input")],
                         [("10", "SCL", "input"), ("9", "SDA", "bidirectional"), None, ("7", "PENIRQ", "output")],
                         top=[("1", "VDD", "power_in")], bottom=[("6", "GND", "power_in")],
                         descr="Nsiway NS2009 4-wire resistive touch controller, I2C (pinout from Lichee Pi Nano; verify package)"))
    left = [("1", "5V", "power_in"), ("2", "GND", "power_in"), ("3", "3V3", "power_out"), ("4", "GPIO4", "bidirectional"),
            ("5", "GPIO3", "bidirectional"), ("6", "GPIO2", "bidirectional"), ("7", "GPIO1", "bidirectional"), ("8", "GPIO0", "bidirectional")]
    right = [("16", "GPIO5", "bidirectional"), ("15", "GPIO6", "bidirectional"), ("14", "GPIO7", "bidirectional"), ("13", "GPIO8", "bidirectional"),
             ("12", "GPIO9", "bidirectional"), ("11", "GPIO10", "bidirectional"), ("10", "GPIO20/RX", "bidirectional"), ("9", "GPIO21/TX", "bidirectional")]
    S.append(rect_symbol("ESP32-C3_SuperMini", "M", "ESP32-C3 SuperMini", "protoboard:ESP32-C3_SuperMini",
                         left, right, descr="ESP32-C3 SuperMini module, 2x8 pins 2.54 mm (pinout to verify against the module)"))
    return S


def write_symbols():
    body = [f1c200s()] + simple_syms()
    txt = '(kicad_symbol_lib (version 20241209) (generator "protoboard_gen") (generator_version "1.0")\n' + "\n".join(body) + "\n)\n"
    with open(os.path.join(LIB, "protoboard.kicad_sym"), "w") as f:
        f.write(txt)


# ---------------------------------------------------------------- footprints

def fp_header(name, descr, attr="through_hole"):
    return ['(footprint %s (version 20241229) (generator "protoboard_gen") (layer "F.Cu")' % q(name),
            '\t(descr %s)' % q(descr),
            '\t(property "Reference" "REF**" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))',
            '\t(property "Value" %s (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))' % q(name),
            '\t(attr %s)' % attr]


def rect(layer, x0, y0, x1, y1, w=0.12):
    return '\t(fp_rect (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (fill no) (layer %s))' % (
        fmt(x0), fmt(y0), fmt(x1), fmt(y1), fmt(w), q(layer))


def text(layer, s, x, y, size=1.0):
    return '\t(fp_text user %s (at %s %s 0) (layer %s) (effects (font (size %s %s) (thickness 0.15))))' % (
        q(s), fmt(x), fmt(y), q(layer), fmt(size), fmt(size))


def tht_pad(num, x, y, shape="circle", d=1.7, drill=1.0):
    return '\t(pad %s thru_hole %s (at %s %s) (size %s %s) (drill %s) (layers "*.Cu" "*.Mask"))' % (
        q(num), shape, fmt(x), fmt(y), fmt(d), fmt(d), fmt(drill))


def flat_pad(num, x, y, out, shape="oval", d=1.7, ext=1.0, drill=1.0):
    # through-hole pad, F.Cu elongated outward by `ext` (past the module edge, so a flat-soldered
    # module gets a fillet and an iron landing); inner layers and B.Cu stay a plain d x d pad
    inner = "rect" if shape == "rect" else "circle"
    return ('\t(pad %s thru_hole %s (at %s %s) (size %s %s) (drill %s (offset %s 0)) (layers "*.Cu" "*.Mask")'
            ' (padstack (mode front_inner_back) (layer "Inner" (shape %s) (size %s %s))'
            ' (layer "B.Cu" (shape %s) (size %s %s))))') % (
        q(num), shape, fmt(x), fmt(y), fmt(d + ext), fmt(d), fmt(drill), fmt(out * ext / 2),
        inner, fmt(d), fmt(d), inner, fmt(d), fmt(d))


def line(layer, x0, y0, x1, y1, w=0.12):
    return '\t(fp_line (start %s %s) (end %s %s) (stroke (width %s) (type solid)) (layer %s))' % (
        fmt(x0), fmt(y0), fmt(x1), fmt(y1), fmt(w), q(layer))


def esp_supermini():
    # Drawn USB-end up. Rows 15.24 mm apart (module 18 x 22.5 mm). Pin 1 = 5V top-left.
    L = fp_header("ESP32-C3_SuperMini", "ESP32-C3 SuperMini, 2x8 2.54 mm through-holes, rows 15.24 mm apart; "
                  "on headers or soldered flat (F.Cu pads run 0.5 mm past the module edge) "
                  "(verify row spacing against the module)")
    xl, xr = -7.62, 7.62
    for i in range(8):
        y = -8.89 + i * G
        L.append(flat_pad(str(i + 1), xl, y, -1, "rect" if i == 0 else "oval"))
        L.append(flat_pad(str(16 - i), xr, y, 1))
    # outline: 18 x 22.5, USB end at top (y=-11.25 .. +11.25); silk sides broken where the pads run out
    L.append(rect("F.Fab", -9, -11.25, 9, 11.25, 0.1))
    for sy in (-1, 1):
        L.append(line("F.SilkS", -9.12, sy * 11.37, 9.12, sy * 11.37))
        for sx in (-1, 1):
            L.append(line("F.SilkS", sx * 9.12, sy * 11.37, sx * 9.12, sy * 10.1))
    L.append(rect("F.CrtYd", -9.75, -12.5, 9.75, 11.75, 0.05))   # USB plug overhang, flat pads
    L.append(rect("F.Fab", -4.5, -12.5, 4.5, -7.5, 0.1))
    L.append(text("F.Fab", "USB", 0, -10))
    L.append(text("F.SilkS", "ANT", 0, 9.6, 0.8))
    # antenna keep-out on inner copper is left to the zone rules in the board
    L.append(')')
    return "\n".join(L)


def protogrid(cols=38, rows=5):
    L = fp_header("Protogrid_%dx%d_P2.54mm" % (cols, rows),
                  "Through-hole prototyping grid, plated, unconnected", attr="through_hole board_only exclude_from_pos_files exclude_from_bom")
    for r in range(rows):
        for c in range(cols):
            L.append(tht_pad("", c * G, r * G, "circle", 1.6, 1.0))
    L.append(rect("F.CrtYd", -1.1, -1.1, (cols - 1) * G + 1.1, (rows - 1) * G + 1.1, 0.05))
    L.append(')')
    return "\n".join(L)


def railstrip(n=32):
    L = fp_header("RailStrip_1x%02d_P2.54mm" % n, "Power rail strip, %d plated holes on one net, 2.54 mm pitch, horizontal" % n)
    for i in range(n):
        L.append(tht_pad(str(i + 1), i * G, 0, "rect" if i == 0 else "circle"))
    L.append(rect("F.CrtYd", -1.25, -1.2, (n - 1) * G + 1.25, 1.2, 0.05))
    L.append(')')
    return "\n".join(L)


def f1c_qfn():
    """Stock QFN-88 10x10 0.4 mm with signal pads narrowed 0.30 -> 0.22 mm (F1C leads are ~0.2 mm):
    0.18 mm gaps instead of 0.10 mm, kinder to stencil + hot-air assembly."""
    src = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Package_DFN_QFN.pretty/" \
          "ArtInChip_QFN-88-1EP_10x10mm_P0.4mm_EP6.74x6.74mm_ThermalVias.kicad_mod"
    t = open(src).read()
    t = t.replace("(size 0.55 0.3)", "(size 0.55 0.22)").replace("(size 0.3 0.55)", "(size 0.22 0.55)")
    t = t.replace('(footprint "ArtInChip_QFN-88-1EP_10x10mm_P0.4mm_EP6.74x6.74mm_ThermalVias"',
                  '(footprint "F1C200s_QFN-88-1EP_10x10mm_P0.4mm_EP6.74x6.74mm_ThermalVias"', 1)
    return t.rstrip()


def write_footprints():
    d = os.path.join(LIB, "protoboard.pretty")
    os.makedirs(d, exist_ok=True)
    for name, body in [("ESP32-C3_SuperMini", esp_supermini()), ("Protogrid_38x5_P2.54mm", protogrid()), ("Protogrid_31x5_P2.54mm", protogrid(31)),
                       ("RailStrip_1x32_P2.54mm", railstrip()), ("RailStrip_1x26_P2.54mm", railstrip(26)),
                       ("F1C200s_QFN-88-1EP_10x10mm_P0.4mm_EP6.74x6.74mm_ThermalVias", f1c_qfn())]:
        with open(os.path.join(d, name + ".kicad_mod"), "w") as f:
            f.write(body + "\n")


if __name__ == "__main__":
    os.makedirs(LIB, exist_ok=True)
    write_symbols()
    write_footprints()
    print("ok")
