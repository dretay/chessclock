"""Load KiCad library symbols (stock + local), flatten 'extends', report pins."""
import copy
import os

from sexp import parse, find, findall, Sym

KICAD_SHARE = "/Applications/KiCad/KiCad.app/Contents/SharedSupport"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_SYM = os.path.join(HERE, "..", "lib", "protoboard.kicad_sym")

_cache = {}


def _lib_path(lib):
    if lib == "protoboard":
        return LOCAL_SYM
    return os.path.join(KICAD_SHARE, "symbols", lib + ".kicad_sym")


def _load_lib(lib):
    if lib not in _cache:
        with open(_lib_path(lib)) as f:
            tree = parse(f.read())[0]
        _cache[lib] = {s[1]: s for s in findall(tree, "symbol")}
    return _cache[lib]


def get_symbol(lib_id):
    """Return a flattened symbol tree named 'lib:name'."""
    lib, name = lib_id.split(":", 1)
    syms = _load_lib(lib)
    sym = copy.deepcopy(syms[name])
    ext = find(sym, "extends")
    if ext:
        parent = get_symbol(lib + ":" + ext[1])
        # child keeps its own properties; graphics/pins come from parent
        child_props = {p[1]: p for p in findall(sym, "property")}
        new = [Sym("symbol"), name]
        for item in parent[2:]:
            if isinstance(item, list) and item[0] == "property":
                new.append(child_props.pop(item[1], item))
            elif isinstance(item, list) and item[0] == "symbol":
                sub = copy.deepcopy(item)
                pname = parent[1].split(":", 1)[1]
                sub[1] = name + sub[1][len(pname):]
                new.append(sub)
            else:
                new.append(item)
        for p in child_props.values():
            new.insert(2, p)
        sym = new
    sym[1] = lib_id
    return sym


def pins(sym):
    """List of dicts: number, name, x, y, angle, type, unit."""
    out = []
    for sub in findall(sym, "symbol"):
        # sub-symbol name: <name>_<unit>_<style>
        parts = sub[1].rsplit("_", 2)
        unit = int(parts[1])
        for p in findall(sub, "pin"):
            at = find(p, "at")
            out.append(dict(
                type=str(p[1]),
                x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,
                name=find(p, "name")[1], number=find(p, "number")[1], unit=unit,
                hidden=any(x == "hide" for x in p) or bool(find(p, "hide")),
            ))
    return out


if __name__ == "__main__":
    import sys
    for lid in sys.argv[1:]:
        s = get_symbol(lid)
        fp = [p for p in findall(s, "property") if p[1] == "Footprint"]
        print("==", lid, fp[0][2] if fp else "")
        for p in sorted(pins(s), key=lambda p: (p["unit"], p["number"].zfill(4))):
            print("  u%d %4s %-14s %-12s (%g,%g) a%g" % (p["unit"], p["number"], p["name"], p["type"], p["x"], p["y"], p["angle"]))
