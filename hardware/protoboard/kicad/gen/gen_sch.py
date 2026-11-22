"""Draw the hierarchical schematic from design.py.

Parts are placed unrotated and shelf-packed per sheet; every pin end gets a
power symbol, a label (local if the net stays on the sheet, global if not) or
a no-connect flag, so connectivity is exact even though nothing is wired.
"""
import os
import uuid

import design
from design import parts, SHEETS, POWER_NETS
from kilib import get_symbol, pins as sym_pins
from sexp import dump, find, findall, q, fmt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PROJECT = "protoboard"
NS = uuid.UUID("6f1c2005-0000-4000-8000-000000000000")
G = 2.54


def uid(*names):
    return str(uuid.uuid5(NS, "/".join(names)))


ROOT_UUID = uid("root")
SHEET_UUID = {name: uid("sheet", name) for name, _ in SHEETS}


def sym_uuid(ref):
    return uid("sym", ref)


def snap(v, g=1.27):
    return round(v / g) * g


# ------------------------------------------------------------------ PWR_FLAGs
FLAGS = {"power": ["GND", "+5V", "+1V1", "+2V5", "+3V3"], "audio": ["AMP_VDD"]}

# nets per sheet -> local vs global
net_sheets = {}
for p in parts:
    for net in p.pins.values():
        net_sheets.setdefault(net, set()).add(p.sheet)


def is_global(net):
    return len(net_sheets[net]) > 1


def text_w(s):
    return len(s) * 1.1 + 3.0


def away_angle(pin_angle):
    """Lib pin angle points from the pin end into the body; return the visual
    direction pointing away from the body (schematic y is flipped)."""
    a = (pin_angle + 180) % 360
    return {0: 0, 180: 180, 90: 90, 270: 270}[int(a)]


class Placed:
    pass


def layout_sheet(sheet_parts):
    """Compute bbox for each part, shelf-pack, return list of (part, x, y)."""
    items = []
    for p in sheet_parts:
        sym = get_symbol(p.lib_id)
        ps = sym_pins(sym)
        xs = [0.0]
        ys = [0.0]
        ext = {"l": 0, "r": 0, "t": 0, "b": 0}
        for pin in ps:
            x, y = pin["x"], -pin["y"]
            xs.append(x)
            ys.append(y)
            net = p.pins.get(pin["number"])
            w = 2.0 if net is None or net in POWER_NETS else text_w(net)
            a = away_angle(pin["angle"])
            if a == 0:
                xs.append(x + w)
            elif a == 180:
                xs.append(x - w)
            elif a == 90:
                ys.append(y - w)
            else:
                ys.append(y + w)
        for r in findall(find(sym, "symbol") or [], "rectangle"):
            pass
        # include body rectangle(s)
        for sub in findall(sym, "symbol"):
            for r in findall(sub, "rectangle"):
                s, e = find(r, "start"), find(r, "end")
                xs += [float(s[1]), float(e[1])]
                ys += [-float(s[2]), -float(e[2])]
        x0, x1 = min(xs) - 4, max(xs) + 12   # room for ref/value text on the right
        y0, y1 = min(ys) - 4, max(ys) + 4
        items.append((p, sym, ps, x0, y0, x1, y1))

    placed = []
    W = 390.0
    cx, cy, row_h = 20.0, 25.0, 0.0
    for p, sym, ps, x0, y0, x1, y1 in items:
        w, h = x1 - x0, y1 - y0
        if cx + w > W and cx > 20:
            cx = 20.0
            cy += row_h + 6
            row_h = 0
        px, py = snap(cx - x0, G), snap(cy - y0, G)
        placed.append((p, sym, ps, px, py))
        cx += w + 4
        row_h = max(row_h, h)
    height = cy + row_h + 20
    return placed, height


def lib_symbols_block(lib_ids):
    out = ["\t(lib_symbols"]
    for lid in sorted(lib_ids):
        s = get_symbol(lid)
        out.append("\t\t" + dump(s, 2))
    out.append("\t)")
    return "\n".join(out)


def prop_line(name, value, x, y, hide=False, justify=None, angle=0):
    eff = "(font (size 1.27 1.27))"
    if justify:
        eff += " (justify %s)" % justify
    if hide:
        eff += " (hide yes)"
    return '\t\t(property %s %s (at %s %s %d) (effects %s))' % (q(name), q(value), fmt(x), fmt(y), angle, eff)


class Sheet:
    def __init__(self, name, title):
        self.name, self.title = name, title
        self.body = []
        self.lib_ids = set()
        self.pwr_n = 0

    def symbol(self, lib_id, ref, value, x, y, footprint="", uuid_=None, dnp=False, fields=None,
               pins_list=None, rot=0, in_bom=True, on_board=True):
        self.lib_ids.add(lib_id)
        sym = get_symbol(lib_id)
        u = uuid_ or uid("sym", self.name, ref)
        lines = ['\t(symbol (lib_id %s) (at %s %s %d) (unit 1) (exclude_from_sim no) (in_bom %s) (on_board %s) (dnp %s) (uuid %s)'
                 % (q(lib_id), fmt(x), fmt(y), rot, "yes" if in_bom else "no", "yes" if on_board else "no",
                    "yes" if dnp else "no", q(u))]
        props = {p[1]: p for p in findall(sym, "property")}
        vals = {"Reference": ref, "Value": value, "Footprint": footprint,
                "Datasheet": props.get("Datasheet", [0, 0, "~"])[2], "Description": props.get("Description", [0, 0, ""])[2]}
        for k, v in vals.items():
            lp = props.get(k)
            if lp is not None:
                at = find(lp, "at")
                eff = find(lp, "effects")
                hidden = bool(eff and (find(eff, "hide") or "hide" in eff)) or k in ("Footprint", "Datasheet", "Description")
                just = find(eff, "justify") if eff else None
                lx, ly = float(at[1]), -float(at[2])
                pa = int(float(at[3])) if len(at) > 3 else 0
                if ref.startswith("#"):
                    hidden = hidden or k == "Reference"
                lines.append(prop_line(k, v, x + lx, y + ly, hidden, " ".join(just[1:]) if just else None, pa))
            else:
                lines.append(prop_line(k, v, x, y, True))
        for k, v in (fields or {}).items():
            lines.append(prop_line(k, v, x, y + 2.54, True))
        for pin in sorted({pp["number"] for pp in sym_pins(sym)}):
            lines.append('\t\t(pin %s (uuid %s))' % (q(pin), q(uid("pin", self.name, ref, pin))))
        lines.append('\t\t(instances (project %s (path %s (reference %s) (unit 1))))'
                     % (q(PROJECT), q("/%s/%s" % (ROOT_UUID, SHEET_UUID[self.name]) if self.name != "root" else "/" + ROOT_UUID), q(ref)))
        lines.append('\t)')
        self.body.append("\n".join(lines))
        return u

    def power(self, net, x, y, away):
        lid = POWER_NETS[net]
        default = 270 if net == "GND" else 90
        rot = (away - default) % 360
        self.pwr_n += 1
        ref = "#PWR%s%03d" % (self.name[:2].upper(), self.pwr_n)
        self.symbol(lid, ref, net, x, y, rot=rot, in_bom=False, on_board=True)

    def flag(self, net, x, y):
        self.pwr_n += 1
        self.symbol("power:PWR_FLAG", "#FLG%s%03d" % (self.name[:2].upper(), self.pwr_n), "PWR_FLAG", x, y,
                    in_bom=False, on_board=True)

    def label(self, net, x, y, angle, glob):
        just = {0: "left", 180: "right", 90: "left", 270: "right"}[angle]
        u = uid("label", self.name, net, fmt(x), fmt(y))
        if glob:
            self.body.append('\t(global_label %s (shape passive) (at %s %s %d) (fields_autoplaced yes) '
                             '(effects (font (size 1.27 1.27)) (justify %s)) (uuid %s) '
                             '(property "Intersheetrefs" "${INTERSHEET_REFS}" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes))))'
                             % (q(net), fmt(x), fmt(y), angle, just, q(u), fmt(x), fmt(y)))
        else:
            self.body.append('\t(label %s (at %s %s %d) (effects (font (size 1.27 1.27)) (justify %s bottom)) (uuid %s))'
                             % (q(net), fmt(x), fmt(y), angle, just, q(u)))

    def wire(self, x0, y0, x1, y1):
        self.body.append('\t(wire (pts (xy %s %s) (xy %s %s)) (stroke (width 0) (type default)) (uuid %s))'
                         % (fmt(x0), fmt(y0), fmt(x1), fmt(y1), q(uid("wire", self.name, fmt(x0), fmt(y0), fmt(x1), fmt(y1)))))

    def nc(self, x, y):
        self.body.append('\t(no_connect (at %s %s) (uuid %s))' % (fmt(x), fmt(y), q(uid("nc", self.name, fmt(x), fmt(y)))))

    def text(self, s, x, y, size=2.0):
        self.body.append('\t(text %s (exclude_from_sim no) (at %s %s 0) (effects (font (size %s %s)) (justify left bottom)) (uuid %s))'
                         % (q(s), fmt(x), fmt(y), fmt(size), fmt(size), q(uid("text", self.name, s[:40], fmt(y)))))

    def write(self, path, paper, page_title, extra_header=""):
        hdr = ['(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")',
               '\t(uuid %s)' % q(ROOT_UUID if self.name == "root" else uid("file", self.name)),
               '\t(paper %s)' % paper,
               '\t(title_block (title %s) (date "2026-11-20") (rev "0.1") (company "") '
               '(comment 1 "Generated by kicad/gen/ from hardware/protoboard/DESIGN.md - edit design.py and regenerate") '
               '(comment 2 %s))' % (q("F1C200s prototyping board - " + page_title), q("Items marked (verify) in DESIGN.md still apply")),
               lib_symbols_block(self.lib_ids)]
        with open(path, "w") as f:
            f.write("\n".join(hdr + self.body + [extra_header, ")"]) + "\n")


def build_child(name, title):
    sp = [p for p in parts if p.sheet == name]
    placed, height = layout_sheet(sp)
    sh = Sheet(name, title)
    sh.text(title, 20, 15, 4)
    for p, sym, ps, x, y in placed:
        sh.symbol(p.lib_id, p.ref, p.value, x, y, footprint=p.footprint, uuid_=sym_uuid(p.ref), dnp=p.dnp,
                  fields=p.fields, in_bom=p.lib_id != "Mechanical:MountingHole" or True)
        done = set()
        allnums = {pp["number"] for pp in ps}
        missing = allnums - set(p.pins) - p.nc
        if missing:
            raise SystemExit("%s (%s): pins without a net or NC: %s" % (p.ref, p.lib_id, sorted(missing)))
        extra = set(p.pins) - allnums
        if extra:
            raise SystemExit("%s: nets on nonexistent pins %s" % (p.ref, sorted(extra)))
        for pin in ps:
            px, py = x + pin["x"], y - pin["y"]
            key = (round(px, 2), round(py, 2))
            if key in done:
                continue
            done.add(key)
            num = pin["number"]
            a = away_angle(pin["angle"])
            if num in p.nc:
                sh.nc(px, py)
                continue
            net = p.pins[num]
            if net in POWER_NETS:
                sh.power(net, px, py, a)
            else:
                sh.label(net, px, py, a, is_global(net))
    # PWR_FLAGs: each on a short wire to a power symbol / label
    fx = 20.32
    fy = snap(height, G)
    for net in FLAGS.get(name, []):
        sh.flag(net, fx, fy)
        sh.wire(fx, fy, fx, fy + 5.08)
        if net in POWER_NETS:
            sh.power(net, fx, fy + 5.08, 270)
        else:
            sh.label(net, fx, fy + 5.08, 270, is_global(net))
        fx += 15.24
    height += 25
    paper = '"A3"' if height < 275 else ('"A2"' if height < 400 else '"A1"')
    sh.write(os.path.join(OUT, name + ".kicad_sch"), paper, title)


def build_root():
    sh = Sheet("root", "Overview")
    x, y = 30.0, 50.0
    for i, (name, title) in enumerate(SHEETS):
        w, h = 60.96, 20.32
        u = SHEET_UUID[name]
        sh.body.append(
            '\t(sheet (at %s %s) (size %s %s) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) (fields_autoplaced yes) '
            '(stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid %s) '
            '(property "Sheetname" %s (at %s %s 0) (effects (font (size 1.27 1.27)) (justify left bottom))) '
            '(property "Sheetfile" %s (at %s %s 0) (effects (font (size 1.27 1.27)) (justify left top))) '
            '(instances (project %s (path %s (page %s)))))'
            % (fmt(x), fmt(y), fmt(w), fmt(h), q(u), q(title), fmt(x), fmt(y - 0.7), q(name + ".kicad_sch"),
               fmt(x), fmt(y + h + 0.6), q(PROJECT), q("/" + ROOT_UUID), q(str(i + 2))))
        x += 75
        if x > 300:
            x = 30.0
            y += 40
    notes = [
        "F1C200s prototyping board - 70 x 90 mm, 4 layers (signal / GND / power / signal)",
        "Spec: hardware/protoboard/DESIGN.md. Generated by kicad/gen/*.py: edit design.py and rerun ./gen/build.sh",
        "Open items (see DESIGN.md): buck / load switch / expander / FPC part choice, FPC position mock-up,",
        "SuperMini pinout + row spacing, NS2009 package, FEL-button approach, PAM8403 SHDN threshold.",
        "ESP32-C3 SuperMini has no EN pin on its headers: ESP_EN goes to a bodge pad (TP) for a wire to the module's EN/RST.",
    ]
    for i, n in enumerate(notes):
        sh.text(n, 30, 150 + i * 6, 2.0)
    sh.write(os.path.join(OUT, PROJECT + ".kicad_sch"), '"A4"', "Overview",
             '\t(sheet_instances (path "/" (page "1")))')


if __name__ == "__main__":
    import json
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache"), exist_ok=True)
    json.dump([p.ref for p in parts], open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "order.json"), "w"))
    for name, title in SHEETS:
        build_child(name, title)
    build_root()
    print("schematic written")
