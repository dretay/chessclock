"""Disney Dream countdown scene: STL + photo livery + procedural paint + ocean + sky.

blender -b -P scene.py -- --out DIR --look day|dusk|night_lit|night_dark|mask [--samples N] [--preview]
Inputs come from THEME_ASSETS (default assets/dream: the STL), THEME_WORK (default
tools/themegen/work/dream: livery/elevation.png and livery/windows.png from build_livery.py)
and HDRI_DIR (default assets/hdri: the Poly Haven skies). build_dream.sh runs all of it.
Writes DIR/<look>.png (800x480). Also writes DIR/scene.json (horizon, funnel
tops in pixels) on every run.
"""
import bpy, bmesh, math, sys, json, os
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "dream"))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "dream"))
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
OUT = arg("--out", "."); LOOK = arg("--look", "day"); SAMPLES = int(arg("--samples", "48"))
STL = arg("--stl", os.path.join(ASSETS, "disney_dream.stl"))
W, H = (400, 240) if "--preview" in argv else (800, 480)
RES = int(arg("--res-scale", "1"))   # render larger, shrink later: crisper edges
SCALE = 340.0 / 24798.0          # model units -> metres (the Dream is 340 m long)

# ------------------------------------------------------------------ reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene

# ------------------------------------------------------------------ ship
bpy.ops.wm.stl_import(filepath=STL)
ship = bpy.context.selected_objects[0]
ship.rotation_euler = (0, 0, math.radians(90))      # bow (model -y) -> +x
ship.scale = (SCALE,) * 3
bpy.context.view_layer.objects.active = ship
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bb = [ship.matrix_world @ Vector(c) for c in ship.bound_box]
xmin = min(v.x for v in bb); xmax = max(v.x for v in bb); zmin = min(v.z for v in bb)
ymid = (min(v.y for v in bb) + max(v.y for v in bb)) / 2
DRAFT = 0.4                                          # sink the flat bottom just under the surface
for v in ship.data.vertices:
    v.co.x -= (xmin + xmax) / 2; v.co.y -= ymid; v.co.z -= zmin + DRAFT
L = xmax - xmin
try:
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(32))   # smooth curved plating, keep real edges
except Exception as e:
    print("smooth by angle unavailable:", e); bpy.ops.object.shade_flat()

bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="LOOSE"); bpy.ops.object.mode_set(mode="OBJECT")
parts = [o for o in scn.objects if o.type == "MESH"]
def bbox(o):
    vs = [o.matrix_world @ v.co for v in o.data.vertices]
    return (Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs))),
            Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs))))
info = sorted(((len(o.data.polygons), o, *bbox(o)) for o in parts), key=lambda t: -t[0])
body = info[0][1]
lifeboats = [t for t in info if t[0] == 1595]
boat_z = min(t[2].z for t in lifeboats) if lifeboats else 15.0
# funnels: the big parts that reach high, away from the body's ends
# the funnels are part of the fused body: centred 50% and 69% of the length back from the bow
XBOW = max(t[3].x for t in info)
FUNNELS = [XBOW - 0.50 * L, XBOW - 0.69 * L]
FUNNEL_HALF, FUNNEL_BEAM, FUNNEL_BASE, PIPES, FUNNEL_TOP = 10.5, 6.5, 42.5, 51.6, 56.8
funnels = []
for t in lifeboats: print("boat", [round(c,1) for c in t[2]], [round(c,1) for c in t[3]])
if "--parts" in argv:
    for t in info:
        if t[2].y < -15 and t[3].z < 25 and t[0] != 1595: print("part", t[0], [round(c,1) for c in t[2]], [round(c,1) for c in t[3]])
print("parts", len(info), "lifeboats", len(lifeboats), "boat_z %.1f" % boat_z, "funnels at x", [round(f, 1) for f in FUNNELS])

# ------------------------------------------------------------------ materials
def node_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return m, nt, out

def principled(nt, color, rough=0.45, metal=0.0):
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    p.inputs["Base Color"].default_value = (*color, 1); p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    return p

def simple(name, color, rough=0.45, metal=0.0):
    m, nt, out = node_mat(name)
    nt.links.new(principled(nt, color, rough, metal).outputs[0], out.inputs[0]); return m

LIVERY = "--no-livery" not in argv
LIVERY_DIR = os.path.join(WORK, "livery")
TEX_X0, TEX_X1, TEX_Z0, TEX_Z1 = -172.0, 172.0, -1.0, 60.0     # must match build_livery.py
NAVY = (0.012, 0.016, 0.035); WHITE = (0.78, 0.78, 0.76); RED = (0.42, 0.02, 0.02)
GOLD = (0.55, 0.32, 0.05); YELLOW = (0.85, 0.55, 0.02); BLACK = (0.02, 0.02, 0.02)
LIT = LOOK == "night_lit"
NIGHT = LOOK.startswith("night")

def hull_mat():
    """Paint the fused body by height: red boot-topping, navy hull, gold
    stripe, white above; windows in the white superstructure (dark glass by
    day, emissive cells at night when LIT)."""
    m, nt, out = node_mat("Body")
    N = nt.nodes; Lk = nt.links.new
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ"); Lk(geo.outputs["Position"], sep.inputs[0])
    nsep = N.new("ShaderNodeSeparateXYZ"); Lk(geo.outputs["Normal"], nsep.inputs[0])
    def math_node(op, a=None, b=None, va=None, vb=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        if a is not None: Lk(a, n.inputs[0])
        elif va is not None: n.inputs[0].default_value = va
        if b is not None: Lk(b, n.inputs[1])
        elif vb is not None: n.inputs[1].default_value = vb
        return n.outputs[0]
    x, z = sep.outputs["X"], sep.outputs["Z"]
    # hull top: flat at boat deck minus a bit, sweeping up toward the bow
    h0 = boat_z - 1.2
    bowness = math_node("MAXIMUM", math_node("DIVIDE", math_node("SUBTRACT", x, vb=L * 0.22), vb=L * 0.28), vb=0.0)
    bowness = math_node("MINIMUM", bowness, vb=1.0)
    hull_top = math_node("ADD", math_node("MULTIPLY", math_node("POWER", bowness, vb=1.6), vb=6.5), vb=h0)
    above = math_node("GREATER_THAN", z, hull_top)                      # 1 = superstructure
    rel = math_node("SUBTRACT", z, hull_top)
    gold = math_node("MULTIPLY", math_node("GREATER_THAN", rel, vb=-0.9), math_node("LESS_THAN", rel, vb=-0.45))
    boot = math_node("LESS_THAN", z, vb=1.4)
    def mix(fac, a, b):
        n = N.new("ShaderNodeMix"); n.data_type = "RGBA"; Lk(fac, n.inputs["Factor"])
        for sock, v in (("A", a), ("B", b)):
            if isinstance(v, tuple): n.inputs[sock].default_value = (*v, 1)
            else: Lk(v, n.inputs[sock])
        return n.outputs["Result"]
    col = mix(above, NAVY, WHITE)
    col = mix(gold, col, GOLD)
    col = mix(boot, col, RED)
    # windows: vertical faces in the superstructure between the boat deck and ~38 m
    side = math_node("LESS_THAN", math_node("ABSOLUTE", nsep.outputs["Z"]), vb=0.3)
    band = math_node("MULTIPLY", math_node("GREATER_THAN", z, vb=boat_z + 2.0), math_node("LESS_THAN", z, vb=boat_z + 22.0))
    deck = math_node("FRACT", math_node("DIVIDE", math_node("SUBTRACT", z, vb=boat_z), vb=2.85))
    row = math_node("MULTIPLY", math_node("GREATER_THAN", deck, vb=0.3), math_node("LESS_THAN", deck, vb=0.72))
    bay = math_node("FRACT", math_node("DIVIDE", x, vb=3.6))
    colm = math_node("MULTIPLY", math_node("GREATER_THAN", bay, vb=0.2), math_node("LESS_THAN", bay, vb=0.8))
    win = math_node("MULTIPLY", math_node("MULTIPLY", side, band), math_node("MULTIPLY", row, colm))
    win = math_node("MULTIPLY", win, above)
    win = math_node("MULTIPLY", win, math_node("LESS_THAN", x, vb=119.0))
    col = mix(win, col, (0.07, 0.09, 0.11))
    # funnels: red with black pipe tops
    y_abs = math_node("ABSOLUTE", sep.outputs["Y"])
    in_f = None
    for fx in FUNNELS:
        near = math_node("LESS_THAN", math_node("ABSOLUTE", math_node("SUBTRACT", x, vb=fx)), vb=FUNNEL_HALF)
        in_f = near if in_f is None else math_node("MAXIMUM", in_f, near)
    in_f = math_node("MULTIPLY", in_f, math_node("LESS_THAN", y_abs, vb=FUNNEL_BEAM))
    col = mix(math_node("MULTIPLY", in_f, math_node("GREATER_THAN", z, vb=FUNNEL_BASE)), col, RED)
    col = mix(math_node("MULTIPLY", in_f, math_node("GREATER_THAN", z, vb=PIPES)), col, BLACK)
    # the photo livery: a side elevation of the real ship, projected across the hull onto
    # side-facing surfaces (paint, scrollwork, name, real windows and balconies)
    tex_fac = None
    if LIVERY:
        uvw = N.new("ShaderNodeCombineXYZ")
        Lk(math_node("DIVIDE", math_node("SUBTRACT", x, vb=TEX_X0), vb=TEX_X1 - TEX_X0), uvw.inputs[0])
        Lk(math_node("DIVIDE", math_node("SUBTRACT", z, vb=TEX_Z0), vb=TEX_Z1 - TEX_Z0), uvw.inputs[1])
        def img_node(name, data=False):
            n = N.new("ShaderNodeTexImage"); n.image = bpy.data.images.load(os.path.join(LIVERY_DIR, name))
            if data: n.image.colorspace_settings.name = "Non-Color"
            n.extension = "CLIP"; n.interpolation = "Cubic"; Lk(uvw.outputs[0], n.inputs["Vector"]); return n
        etex = img_node("elevation.png"); wtex = img_node("windows.png", data=True)
        ny = math_node("ABSOLUTE", nsep.outputs["Y"])
        facing = math_node("MINIMUM", math_node("MAXIMUM", math_node("DIVIDE", math_node("SUBTRACT", ny, vb=0.06), vb=0.12), vb=0.0), vb=1.0)   # flared bow plating counts as side
        tex_fac = math_node("MULTIPLY", etex.outputs["Alpha"], facing)
        dim = N.new("ShaderNodeMix"); dim.data_type = "RGBA"; dim.blend_type = "MULTIPLY"; dim.inputs["Factor"].default_value = 1.0
        Lk(etex.outputs["Color"], dim.inputs["A"]); dim.inputs["B"].default_value = (0.86, 0.86, 0.86, 1)   # the photo already has daylight in it
        col = mix(tex_fac, col, dim.outputs["Result"])
        win = math_node("MULTIPLY", win, math_node("SUBTRACT", va=1.0, b=tex_fac))
        win = math_node("ADD", win, math_node("MULTIPLY", wtex.outputs["Color"], tex_fac))
    # bridge and forward lounges: rows of wide windows on the forward-facing superstructure,
    # which a side photo can't reach
    fwd_face = math_node("GREATER_THAN", nsep.outputs["X"], vb=0.45)
    fwd_zone = math_node("MULTIPLY", math_node("GREATER_THAN", x, vb=L * 0.12), math_node("MULTIPLY",
               math_node("GREATER_THAN", z, vb=boat_z + 6.0), math_node("LESS_THAN", z, vb=46.0)))
    fdeck = math_node("FRACT", math_node("DIVIDE", math_node("SUBTRACT", z, vb=boat_z), vb=2.85))
    frow = math_node("MULTIPLY", math_node("GREATER_THAN", fdeck, vb=0.22), math_node("LESS_THAN", fdeck, vb=0.8))
    mull = math_node("LESS_THAN", math_node("FRACT", math_node("DIVIDE", sep.outputs["Y"], vb=2.2)), vb=0.9)   # mullions
    fwin = math_node("MULTIPLY", math_node("MULTIPLY", fwd_face, fwd_zone), math_node("MULTIPLY", frow, mull))
    fwin = math_node("MULTIPLY", fwin, above)
    # the forward face: three long window strips on the sloped front (about 24-31 m up), then the
    # bridge: a lower band running out onto the bridge wings and an upper wraparound band.
    # Real glass (dark and glossy, so it reflects the sky); unlit at night like the real ship's bridge.
    ynode = sep.outputs["Y"]; yabs = math_node("ABSOLUTE", ynode)
    front = math_node("MULTIPLY", math_node("GREATER_THAN", nsep.outputs["X"], vb=0.3), math_node("GREATER_THAN", x, vb=88.0))
    def band(z0, z1, half_width):
        return math_node("MULTIPLY", math_node("MULTIPLY", math_node("GREATER_THAN", z, vb=z0), math_node("LESS_THAN", z, vb=z1)),
                         math_node("LESS_THAN", yabs, vb=half_width))
    def mullions(pitch, frac):
        return math_node("LESS_THAN", math_node("FRACT", math_node("DIVIDE", ynode, vb=pitch)), vb=frac)
    strips = math_node("MAXIMUM", math_node("MAXIMUM", band(24.7, 26.1, 12.0), band(26.9, 28.3, 13.0)), band(29.1, 30.5, 14.0))
    strips = math_node("MULTIPLY", strips, mullions(1.7, 0.9))
    bridge = math_node("MAXIMUM", math_node("MULTIPLY", band(34.4, 36.2, 21.0), mullions(1.25, 0.88)),
                       math_node("MULTIPLY", band(37.4, 39.6, 17.5), mullions(1.6, 0.9)))
    glass = math_node("MULTIPLY", front, math_node("MAXIMUM", strips, bridge))
    col = mix(glass, col, (0.025, 0.035, 0.05))
    # aft terraces: balcony glass on the aft-facing steps, which the side photo can't see either
    aft_face = math_node("LESS_THAN", nsep.outputs["X"], vb=-0.45)
    aft_zone = math_node("MULTIPLY", math_node("LESS_THAN", x, vb=-L * 0.3), math_node("MULTIPLY",
               math_node("GREATER_THAN", z, vb=boat_z + 1.0), math_node("LESS_THAN", z, vb=44.0)))
    arow = math_node("MULTIPLY", math_node("GREATER_THAN", fdeck, vb=0.3), math_node("LESS_THAN", fdeck, vb=0.78))
    amull = math_node("LESS_THAN", math_node("FRACT", math_node("DIVIDE", sep.outputs["Y"], vb=3.6)), vb=0.82)
    awin = math_node("MULTIPLY", math_node("MULTIPLY", aft_face, aft_zone), math_node("MULTIPLY", arow, amull))
    col = mix(awin, col, (0.07, 0.09, 0.11))
    win = math_node("MAXIMUM", win, awin)
    # the forward mooring deck: a recess in the bow deck near the tip, red-brown inside with a shadowed rim
    up = math_node("GREATER_THAN", nsep.outputs["Z"], vb=0.6)
    ex = math_node("DIVIDE", math_node("SUBTRACT", x, vb=XBOW - 12.5), vb=7.5)
    ey = math_node("DIVIDE", ynode, vb=3.6)
    ell = math_node("ADD", math_node("MULTIPLY", ex, ex), math_node("MULTIPLY", ey, ey))
    on_deck = math_node("MULTIPLY", up, math_node("GREATER_THAN", z, vb=14.0))
    recess = math_node("MULTIPLY", on_deck, math_node("LESS_THAN", ell, vb=1.0))
    rim = math_node("MULTIPLY", recess, math_node("GREATER_THAN", ell, vb=0.72))
    col = mix(recess, col, (0.32, 0.11, 0.06))
    col = mix(rim, col, (0.04, 0.035, 0.035))
    col = mix(boot, col, RED)          # the red waterline band, over the photo
    if "--debug-fac" in argv and tex_fac is not None:
        # diagnostic: red = photo paint used, green = surface counts as side-facing, blue = photo has ship here
        dbg = N.new("ShaderNodeCombineXYZ"); Lk(tex_fac, dbg.inputs[0]); Lk(facing, dbg.inputs[1]); Lk(etex.outputs["Alpha"], dbg.inputs[2])
        em = N.new("ShaderNodeEmission"); Lk(dbg.outputs[0], em.inputs[0]); Lk(em.outputs[0], out.inputs[0]); return m
    p = principled(nt, (1, 1, 1), 0.35); Lk(col, p.inputs["Base Color"])
    rough = mix(math_node("MAXIMUM", win, glass), (0.62, 0.62, 0.62), (0.04, 0.04, 0.04))   # painted steel is fairly matte
    Lk(rough, p.inputs["Roughness"])
    p.inputs["Specular IOR Level"].default_value = 0.35
    if LIT:
        # every window lit (the device switches cells on/off from lit vs dark plates);
        # warmth and brightness vary per cabin
        cell = N.new("ShaderNodeCombineXYZ")
        Lk(math_node("FLOOR", math_node("DIVIDE", x, vb=3.6)), cell.inputs[0])
        Lk(math_node("FLOOR", math_node("DIVIDE", z, vb=2.85)), cell.inputs[1])
        Lk(math_node("SIGN", sep.outputs["Y"]), cell.inputs[2])
        noise = N.new("ShaderNodeTexWhiteNoise"); noise.noise_dimensions = "3D"; Lk(cell.outputs[0], noise.inputs["Vector"])
        ramp = N.new("ShaderNodeValToRGB"); Lk(noise.outputs["Value"], ramp.inputs[0])
        ramp.color_ramp.elements[0].color = (1.0, 0.55, 0.22, 1); ramp.color_ramp.elements[1].color = (1.0, 0.82, 0.6, 1)
        Lk(ramp.outputs[0], p.inputs["Emission Color"])
        strength = math_node("MULTIPLY", win, math_node("ADD", math_node("MULTIPLY", noise.outputs["Value"], vb=1.6), vb=0.9))
        Lk(strength, p.inputs["Emission Strength"])
    Lk(p.outputs[0], out.inputs[0])
    return m

def funnel_mat(zlo, zhi):
    m, nt, out = node_mat("Funnel")
    N = nt.nodes; Lk = nt.links.new
    geo = N.new("ShaderNodeNewGeometry"); sep = N.new("ShaderNodeSeparateXYZ"); Lk(geo.outputs["Position"], sep.inputs[0])
    gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; Lk(sep.outputs["Z"], gt.inputs[0])
    gt.inputs[1].default_value = zlo + (zhi - zlo) * 0.72
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; Lk(gt.outputs[0], mx.inputs["Factor"])
    mx.inputs["A"].default_value = (*RED, 1); mx.inputs["B"].default_value = (*BLACK, 1)
    p = principled(nt, RED, 0.4); Lk(mx.outputs["Result"], p.inputs["Base Color"]); Lk(p.outputs[0], out.inputs[0])
    return m

def lifeboat_mat():
    """Enclosed lifeboat: Disney yellow canopy, a darker hull below a rub rail, a row of small windows."""
    m, nt, out = node_mat("Lifeboat")
    N = nt.nodes; Lk = nt.links.new
    tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); Lk(tc.outputs["Generated"], sep.inputs[0])
    geo = N.new("ShaderNodeNewGeometry"); nsep = N.new("ShaderNodeSeparateXYZ"); Lk(geo.outputs["Normal"], nsep.inputs[0])
    def mth(op, a, b=None, va=None, vb=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        if a is not None: Lk(a, n.inputs[0])
        else: n.inputs[0].default_value = va
        if b is not None: Lk(b, n.inputs[1])
        elif vb is not None: n.inputs[1].default_value = vb
        return n.outputs[0]
    def band(v, lo, hi): return mth("MULTIPLY", mth("GREATER_THAN", v, vb=lo), mth("LESS_THAN", v, vb=hi))
    z, x = sep.outputs["Z"], sep.outputs["X"]
    side = mth("GREATER_THAN", mth("ABSOLUTE", nsep.outputs["Y"]), vb=0.55)
    hull = mth("LESS_THAN", z, vb=0.30)
    rail = band(z, 0.30, 0.36)
    # windows: 0.55-0.68 up the side, 15 along it, kept off the rounded ends
    wx = mth("LESS_THAN", mth("FRACT", mth("MULTIPLY", x, vb=15.0)), vb=0.55)
    win = mth("MULTIPLY", mth("MULTIPLY", band(z, 0.55, 0.68), band(x, 0.12, 0.88)), mth("MULTIPLY", wx, side))
    def mixc(fac, a_col, b_sock=None, b_col=None):
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; Lk(fac, mx.inputs["Factor"])
        if isinstance(a_col, tuple): mx.inputs["A"].default_value = (*a_col, 1)
        else: Lk(a_col, mx.inputs["A"])
        mx.inputs["B"].default_value = (*b_col, 1)
        return mx.outputs["Result"]
    c = mixc(hull, (0.80, 0.42, 0.02), b_col=(0.62, 0.30, 0.015))
    c = mixc(rail, c, b_col=(0.05, 0.05, 0.05))
    c = mixc(win, c, b_col=(0.02, 0.025, 0.03))
    p = principled(nt, YELLOW, 0.32); Lk(c, p.inputs["Base Color"])
    p.inputs["Coat Weight"].default_value = 0.3
    Lk(p.outputs[0], out.inputs[0])
    return m

# lifeboats and their davits: moved to where the photo has them (the model's are a deck low and too
# closely spaced), lengthened to the photo's ~12.5 m; the model's forward-most pair has no boat in the photo
BOAT_X = [-93.8, -74.0, -56.6, -41.6, -25.7, -9.55, 7.55, 25.7]
BOAT_Z0, BOAT_SX, BOAT_SZ = 15.9, 1.15, 1.1
davits = [t for t in info if t[0] in (556, 558)]
moved_davits = set()
for sgn in (-1, 1):
    side_boats = sorted((t for t in lifeboats if (t[2].y + t[3].y) * sgn > 0), key=lambda t: t[2].x)
    for k, t in enumerate(side_boats):
        o = t[1]; cx = (t[2].x + t[3].x) / 2; z0 = t[2].z
        mine = [d for d in davits if (d[2].y + d[3].y) * sgn > 0 and t[2].x <= (d[2].x + d[3].x) / 2 <= t[3].x]
        if k >= len(BOAT_X):
            o.hide_render = True
            for d in mine: d[1].hide_render = True; moved_davits.add(id(d))
            continue
        dx, dz = BOAT_X[k] - cx, BOAT_Z0 - z0
        for v in o.data.vertices:
            v.co.x = BOAT_X[k] + (v.co.x - cx) * BOAT_SX; v.co.z = BOAT_Z0 + (v.co.z - z0) * BOAT_SZ
        o.data.update()
        for d in mine:
            for v in d[1].data.vertices: v.co.x += dx; v.co.z += dz
            d[1].data.update(); moved_davits.add(id(d))
print("davits moved", len(moved_davits), "of", len(davits))

white = simple("White", WHITE, 0.4); yellow = lifeboat_mat()
body.data.materials.append(hull_mat())
for t in info[1:]:
    o = t[1]
    # the model's raised "Disney Dream" lettering (bow and stern) sits a deck too high: the photo has the real name
    if LIVERY and t[0] < 600 and 11.0 < t[2].z and t[3].z < 15.8 and (70 < t[2].x < 87 or -161 < t[2].x < -156):
        o.hide_render = True; continue
    if t in lifeboats:
        o.data.materials.append(yellow)
    elif t in funnels: o.data.materials.append(funnel_mat(t[2].z, t[3].z))
    else: o.data.materials.append(white)

# ------------------------------------------------------------------ ocean
bpy.ops.mesh.primitive_plane_add(size=2)
sea = bpy.context.active_object; sea.name = "Ocean"
oc = sea.modifiers.new("Ocean", "OCEAN")
oc.geometry_mode = "GENERATE"; oc.size = 1.0; oc.spatial_size = 240; oc.repeat_x = 14; oc.repeat_y = 14
oc.resolution = 14; oc.wave_scale = 0.55; oc.choppiness = 0.9; oc.wind_velocity = 9; oc.time = 4.0
oc.wave_alignment = 0.3; oc.wave_direction = math.radians(20)
sea.location = (-1680, -900, 0)
far = bpy.ops.mesh.primitive_plane_add(size=40000, location=(0, 0, -0.6)); far = bpy.context.active_object
m, nt, out = node_mat("Water")
p = principled(nt, (0.004, 0.022, 0.055), 0.06); p.inputs["IOR"].default_value = 1.333
# fine ripples everywhere, so the flat far sea isn't a mirror
tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.35, 0.9, 0.35)
nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 1.0; nz.inputs["Detail"].default_value = 6
bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.25
nt.links.new(tc.outputs["Object"], mp.inputs[0]); nt.links.new(mp.outputs[0], nz.inputs["Vector"])
nt.links.new(nz.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs[0], p.inputs["Normal"])
nt.links.new(p.outputs[0], out.inputs[0])
sea.data.materials.append(m); far.data.materials.append(m)

# ------------------------------------------------------------------ world + light
world = bpy.data.worlds.new("World"); scn.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wn.clear()
wout = wn.new("ShaderNodeOutputWorld"); bg = wn.new("ShaderNodeBackground")
world.node_tree.links.new(bg.outputs[0], wout.inputs[0])
SUN_ROT = math.radians(205)       # sun behind the camera's left shoulder
def sky(elev_deg, strength=1.0):
    st = wn.new("ShaderNodeTexSky")
    for kind in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try: st.sky_type = kind; break
        except TypeError: pass
    for attr, val in (("sun_elevation", math.radians(elev_deg)), ("sun_rotation", SUN_ROT), ("altitude", 30.0)):
        if hasattr(st, attr): setattr(st, attr, val)
    world.node_tree.links.new(st.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = strength
    print("sky", st.sky_type)

HDRI_DIR = os.environ.get("HDRI_DIR", os.path.join(REPO, "assets", "hdri"))
SKIES = {   # photographed skies (Poly Haven, CC0): file, strength, rotation (deg), exposure
    "day":  (arg("--sky-day", "kloofendal_48d_partly_cloudy_puresky"), 1.0, float(arg("--rot", "90")), float(arg("--exp", "-0.3"))),
    "dusk": (arg("--sky-dusk", "qwantani_sunset_puresky"), 1.0, float(arg("--rot", "196")), float(arg("--exp", "-2.3"))),
    "night": ("qwantani_night_puresky", 1.0, float(arg("--rot", "0")), float(arg("--exp", "0"))),
}
def env(name, strength, rot):
    tex = wn.new("ShaderNodeTexEnvironment"); tex.image = bpy.data.images.load(os.path.join(HDRI_DIR, name + ".hdr"))
    tc = wn.new("ShaderNodeTexCoord"); mp = wn.new("ShaderNodeMapping"); mp.inputs["Rotation"].default_value = (0, 0, math.radians(rot))
    world.node_tree.links.new(tc.outputs["Generated"], mp.inputs[0]); world.node_tree.links.new(mp.outputs[0], tex.inputs["Vector"])
    world.node_tree.links.new(tex.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = strength
if NIGHT or LOOK == "mask":
    # a deep-blue moonlit night (the photographed night sky came out grey-brown); the device adds stars
    EXPOSURE = 0.0
    bg.inputs[0].default_value = (0.004, 0.008, 0.02, 1); bg.inputs[1].default_value = 1.0
    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(60), 0, math.radians(150)))
    moon = bpy.context.active_object; moon.data.energy = float(arg("--moon", "0.5")); moon.data.color = (0.65, 0.75, 1.0); moon.data.angle = math.radians(0.6)
else:
    sky_name, sky_strength, sky_rot, EXPOSURE = SKIES[LOOK]
    env(sky_name, sky_strength, sky_rot)

# ------------------------------------------------------------------ camera
bpy.ops.object.camera_add()
cam = bpy.context.active_object; scn.camera = cam
cam.data.lens = float(arg("--lens", "55")); cam.data.clip_end = 50000
cam.data.shift_y = float(arg("--shift", "0.1"))   # more sky, same perspective
# 3/4 aerial from the starboard bow quarter, like the photograph
AZ, EL, DIST = math.radians(float(arg("--az", "28"))), math.radians(float(arg("--el", "6"))), float(arg("--dist", "535"))
target = Vector(tuple(float(c) for c in arg("--target", "12,0,16").split(",")))
cam_pos = target + Vector((math.sin(AZ) * math.cos(EL), -math.cos(AZ) * math.cos(EL), math.sin(EL))) * DIST
cam.location = cam_pos
cam.rotation_euler = (target - cam_pos).to_track_quat("-Z", "Y").to_euler()

# ------------------------------------------------------------------ render
scn.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"; prefs.get_devices()
    for d in prefs.devices: d.use = True
    scn.cycles.device = "GPU"
except Exception as e:
    print("GPU unavailable:", e)
scn.cycles.samples = SAMPLES; scn.cycles.use_denoising = True
scn.render.resolution_x, scn.render.resolution_y = W * RES, H * RES; scn.render.resolution_percentage = 100
scn.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in scn.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
scn.view_settings.exposure = EXPOSURE
for look in ([arg("--tone")] if arg("--tone") else []) + ["AgX - High Contrast", "High Contrast", "Medium High Contrast"]:
    try: scn.view_settings.look = look; break
    except TypeError: pass
print("look", scn.view_settings.look)
scn.render.image_settings.file_format = "PNG"
for name in os.environ.get("HIDE", "").split(","):
    if name == "far": far.hide_render = True
    if name == "sea": sea.hide_render = True
if LOOK == "mask":
    # ship alone, everything else transparent: the device's water must not move under the ship
    sea.hide_render = True; far.hide_render = True; scn.render.film_transparent = True
    scn.render.image_settings.color_mode = "RGBA"
scn.render.filepath = os.path.join(OUT, LOOK + ".png")
if "--info" not in argv:
    bpy.ops.render.render(write_still=True)

# where things land on screen
bpy.context.view_layer.update()
def px(p):
    v = world_to_camera_view(scn, cam, p); return [round(v.x * W, 1), round((1 - v.y) * H, 1)]
fwd = (target - cam_pos); fwd.z = 0; fwd.normalize()
far_pt = cam_pos + fwd * 20000; far_pt.z = 0
stacks = [px(Vector((fx, 0, FUNNEL_TOP))) for fx in FUNNELS]
# bow and stern at the waterline (camera side), the forward mast top, and the AquaDuck tube's path
bvs = [body.matrix_world @ v.co for v in body.data.vertices]
wl = [v for v in bvs if v.z < 1.5]
bow = px(max(wl, key=lambda v: v.x))
near_side = min(v.y for v in bvs)
stern = px(Vector((XBOW - L + 2, near_side, 0.6)))
fwd = [v for v in bvs if v.x > XBOW - 0.42 * L]
mast = px(max(fwd, key=lambda v: v.z))
tube = next(t for t in info if t[0] == 3112)[1]
tv = sorted((tube.matrix_world @ v.co for v in tube.data.vertices), key=lambda v: v.x)
path = []
for k in range(14):
    seg = tv[k * len(tv) // 14:(k + 1) * len(tv) // 14]
    c = sum(seg, Vector()) / len(seg); c.z = max(v.z for v in seg); path.append(px(c))
data = {"horizon": px(far_pt)[1], "stacks": stacks, "bow": bow, "stern": stern, "mast": mast, "tube": path}
tip = max(bvs, key=lambda v: v.x)
data["model"] = {"xbow": XBOW, "L": L, "xstern": min(v.x for v in bvs), "bow_tip": [tip.x, tip.z],
                 "bow_wl_x": max(wl, key=lambda v: v.x).x, "funnels": FUNNELS, "funnel_top": FUNNEL_TOP, "top": max(v.z for v in bvs)}
json.dump(data, open(os.path.join(OUT, "scene.json"), "w"))
print("scene.json", data)
