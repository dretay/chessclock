"""Cinderella Castle countdown scene (the castle module's): the user's STL, painted by rules, on a
plaza, under a photographed sky. One camera for every look, so the plates line up exactly.

    Blender -b -P tools/themegen/castle/scene.py -- --look day [--samples 64] [--res 2] [--out DIR]
    looks: day, dusk, night, mask (the castle alone, for the device's fireworks to go behind)

Inputs: THEME_ASSETS (default assets/castle): disney_castle_fixed_v2.stl (the user's own model);
assets/hdri/*.hdr (Poly Haven, CC0, shared with the ship). Output: THEME_WORK/renders/LOOK.png
(default tools/themegen/work/castle) at 800x480 x --res, and positions.json (where things land on
screen). The reference photos in assets/castle/ are for judging colours and lighting by eye.

The model: one watertight shell, Z up, its front (the plaza side, with the archway) facing +X,
standing on a print base whose top (the forecourt) is at z=15. Here it's turned to face the camera
(-Y), the forecourt put at z=0 and scaled to metres (the real castle is 57.6 m tall).
"""
import json, math, os, sys
import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "castle"))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "castle"))
OUT = arg("--out", os.path.join(WORK, "renders")); os.makedirs(OUT, exist_ok=True)
LOOK = arg("--look", "day"); SAMPLES = int(arg("--samples", "64")); RES = int(arg("--res", "2"))
W, H = 800, 480
STL = arg("--stl", os.path.join(ASSETS, "disney_castle_fixed_v2.stl"))

# ------------------------------------------------------------------ the model
bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
bpy.ops.wm.stl_import(filepath=STL)
castle = bpy.context.selected_objects[0]; castle.name = "castle"
FORECOURT_Z, CENTRE = 15.0, Vector((146.0, -348.0))       # (measured: the base's top; the footprint's middle)
SCALE = 57.6 / (121.84 - FORECOURT_Z)                      # metres per model unit
castle.data.transform(Matrix.Translation((-CENTRE.x, -CENTRE.y, -FORECOURT_Z)))
castle.data.transform(Matrix.Rotation(math.radians(-90), 4, "Z"))     # front (+X) -> towards the camera (-Y)
castle.data.transform(Matrix.Scale(SCALE, 4))
for p in castle.data.polygons: p.use_smooth = False
TOP = 57.6

# the windows: the back of a recess in a wall. A wall face is one if, from just in front of it, it
# looks out into open air (nothing within OPEN metres straight ahead: not a wall behind railings)
# and is boxed in close on all four sides (sill below, lintel above, jambs left and right, within
# HALF_H / HALF_W metres: not a battlement gap, which is open above, nor the archway, which is wide).
# These faces get their own material, which the "windows" look renders white on black (the
# device's window light, like the ship's cabins).
from mathutils.bvhtree import BVHTree
HALF_W, HALF_H, OPEN = float(arg("--win-w", "1.0")), float(arg("--win-h", "3.5")), float(arg("--win-open", "3.0"))
me = castle.data
bvh = BVHTree.FromPolygons([v.co for v in me.vertices], [p.vertices for p in me.polygons])
UP = Vector((0, 0, 1))
WINDOW_FACES = set()
for p in me.polygons:
    n = p.normal
    if abs(n.z) > 0.25 or p.center.z < float(arg("--win-min-z", "9")): continue   # walls above the forecourt
    q = p.center + n * float(arg("--win-step", "0.04"))
    if bvh.ray_cast(q, n, OPEN)[0] is not None: continue                # something in front: not a window
    t = n.cross(UP).normalized()
    up, down = bvh.ray_cast(q, UP, HALF_H), bvh.ray_cast(q, -UP, HALF_H)
    # a lintel (or the arch's underside) above, facing down; a sill below, facing up: not a roof's underside
    if up[0] is None or down[0] is None or up[1].z > -0.5 or down[1].z < 0.5: continue
    if all(bvh.ray_cast(q, d, HALF_W)[0] is not None for d in (t, -t)):
        WINDOW_FACES.add(p.index)
print("windows: %d recessed faces of %d" % (len(WINDOW_FACES), len(me.polygons)))

def node_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); return m, nt, out

# the castle's paint, by rules: roofs are the faces tilted up (the cones), gold near the tops,
# rose walls above the grey-blue bastions, stone on anything flat on top
m, nt, out = node_mat("castle")
geo = nt.nodes.new("ShaderNodeNewGeometry")
def sep(sock):
    s = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(sock, s.inputs[0]); return s
def math_(op, a=None, b=None, va=None, vb=None):
    n = nt.nodes.new("ShaderNodeMath"); n.operation = op
    if a is not None: nt.links.new(a, n.inputs[0])
    else: n.inputs[0].default_value = va
    if b is not None: nt.links.new(b, n.inputs[1])
    elif vb is not None: n.inputs[1].default_value = vb
    return n.outputs[0]
def band(v, lo, hi): return math_("MULTIPLY", math_("GREATER_THAN", v, vb=lo), math_("LESS_THAN", v, vb=hi))
def smooth(v, lo, hi):
    n = nt.nodes.new("ShaderNodeMapRange"); n.interpolation_type = "SMOOTHSTEP"
    nt.links.new(v, n.inputs["Value"]); n.inputs["From Min"].default_value = lo; n.inputs["From Max"].default_value = hi
    return n.outputs[0]
def rgb(c):
    n = nt.nodes.new("ShaderNodeRGB"); n.outputs[0].default_value = (*c, 1); return n.outputs[0]
def mixc(fac, a, b):
    n = nt.nodes.new("ShaderNodeMix"); n.data_type = "RGBA"
    nt.links.new(fac, n.inputs["Factor"]); nt.links.new(a, n.inputs[6]); nt.links.new(b, n.inputs[7]); return n.outputs[2]
nz = sep(geo.outputs["Normal"]).outputs["Z"]; z = sep(geo.outputs["Position"]).outputs["Z"]
h = math_("DIVIDE", z, vb=TOP)
roof = math_("MULTIPLY", smooth(nz, 0.05, 0.10), math_("LESS_THAN", nz, vb=0.96))      # (spires are steep: barely tilted up)
flat = math_("GREATER_THAN", nz, vb=0.96)
gold = math_("MAXIMUM", math_("MULTIPLY", roof, smooth(h, 0.74, 0.80)), smooth(h, 0.90, 0.92))
STONE, STONE2, ROSE, ROSE2 = (0.46, 0.44, 0.42), (0.56, 0.54, 0.50), (0.82, 0.54, 0.50), (0.90, 0.64, 0.58)   # (warm grey stone)
BLUE, GOLD, CAP = (0.035, 0.07, 0.42), (0.80, 0.58, 0.22), (0.50, 0.50, 0.51)
# stone courses on the walls whichever way they face: bricks on (x + y, z), ~0.6 m courses
pos = geo.outputs["Position"]; ps = sep(pos)
uv = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(math_("ADD", ps.outputs["X"], ps.outputs["Y"]), uv.inputs[0]); nt.links.new(ps.outputs["Z"], uv.inputs[1])
def bricks(c1, c2):
    b = nt.nodes.new("ShaderNodeTexBrick"); nt.links.new(uv.outputs[0], b.inputs["Vector"])
    b.inputs["Scale"].default_value = 1.0; b.inputs["Brick Width"].default_value = 1.3; b.inputs["Row Height"].default_value = 0.6
    b.inputs["Mortar Size"].default_value = 0.035; b.inputs["Color1"].default_value = (*c1, 1); b.inputs["Color2"].default_value = (*c2, 1)
    b.inputs["Mortar"].default_value = tuple(min(1.0, v * 1.25) for v in c2) + (1,); b.inputs["Bias"].default_value = -0.2
    return b
lo, hi = bricks(STONE, STONE2), bricks(ROSE, ROSE2)
wall = mixc(smooth(h, 0.30, 0.34), lo.outputs["Color"], hi.outputs["Color"])
col = mixc(roof, wall, rgb(BLUE)); col = mixc(flat, col, rgb(CAP)); col = mixc(gold, col, rgb(GOLD))
p = nt.nodes.new("ShaderNodeBsdfPrincipled"); nt.links.new(col, p.inputs["Base Color"])
nt.links.new(gold, p.inputs["Metallic"])
p.inputs["Roughness"].default_value = 0.6
bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.25; bump.inputs["Distance"].default_value = 0.03
nt.links.new(math_("MULTIPLY", math_("MAXIMUM", math_("SUBTRACT", va=1.0, b=roof), math_("SUBTRACT", va=1.0, b=flat)) if False else math_("SUBTRACT", va=1.0, b=roof), lo.outputs["Fac"]), bump.inputs["Height"])
nt.links.new(bump.outputs[0], p.inputs["Normal"])
nt.links.new(p.outputs[0], out.inputs[0]); castle.data.materials.append(m)
WINDOWS_LOOK = LOOK == "windows"
wm_, wnt, wout = node_mat("windowglass")
if WINDOWS_LOOK:
    we = wnt.nodes.new("ShaderNodeEmission"); we.inputs["Color"].default_value = (1, 1, 1, 1); we.inputs["Strength"].default_value = 1.0
    wnt.links.new(we.outputs[0], wout.inputs[0])
else:
    wp = wnt.nodes.new("ShaderNodeBsdfPrincipled"); wp.inputs["Base Color"].default_value = (0.05, 0.06, 0.09, 1)
    wp.inputs["Roughness"].default_value = 0.15; wnt.links.new(wp.outputs[0], wout.inputs[0])
castle.data.materials.append(wm_)
for i in WINDOW_FACES: castle.data.polygons[i].material_index = 1
if WINDOWS_LOOK:                         # everything that isn't a window: black, but still in front of things
    hm, hnt, hout = node_mat("black"); hb = hnt.nodes.new("ShaderNodeHoldout"); hnt.links.new(hb.outputs[0], hout.inputs[0])
    castle.data.materials[0] = hm

# the plaza: paving stones out to ~60 m, then lawn with some life in it (a stand-in for the hub)
bpy.ops.mesh.primitive_plane_add(size=2000, location=(0, 0, -0.02)); ground = bpy.context.active_object; ground.name = "ground"
m, nt, out = node_mat("ground")
p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Roughness"].default_value = 0.85
tc = nt.nodes.new("ShaderNodeTexCoord")
def gnode(kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items(): n.inputs[k].default_value = v
    return n
def lnk(a, b): nt.links.new(a, b)
d = nt.nodes.new("ShaderNodeVectorMath"); d.operation = "LENGTH"; lnk(tc.outputs["Object"], d.inputs[0])   # metres from the middle
edge = nt.nodes.new("ShaderNodeMapRange"); lnk(d.outputs["Value"], edge.inputs["Value"])
edge.inputs["From Min"].default_value = 900; edge.inputs["From Max"].default_value = 901     # (all paving: lawns are their own)
# pavers: warm stone in a running bond, each a little different
pav = gnode("ShaderNodeTexBrick", Scale=1.0, **{"Brick Width": 0.9, "Row Height": 0.45, "Mortar Size": 0.02, "Bias": 0.0})
pav.inputs["Color1"].default_value = (0.30, 0.27, 0.23, 1); pav.inputs["Color2"].default_value = (0.35, 0.31, 0.27, 1)
pav.inputs["Mortar"].default_value = (0.42, 0.39, 0.35, 1); lnk(tc.outputs["Object"], pav.inputs["Vector"])
# grass: patchy colour at two scales, and fine blades as a bump
n1 = gnode("ShaderNodeTexNoise", Scale=0.08, Detail=4.0); n2 = gnode("ShaderNodeTexNoise", Scale=2.5, Detail=8.0)
lnk(tc.outputs["Object"], n1.inputs["Vector"]); lnk(tc.outputs["Object"], n2.inputs["Vector"])
gr = nt.nodes.new("ShaderNodeValToRGB"); lnk(n1.outputs["Fac"], gr.inputs[0])
gr.color_ramp.elements[0].position = 0.35; gr.color_ramp.elements[0].color = (0.05, 0.11, 0.03, 1)
gr.color_ramp.elements[1].position = 0.65; gr.color_ramp.elements[1].color = (0.12, 0.20, 0.05, 1)
fine = nt.nodes.new("ShaderNodeMix"); fine.data_type = "RGBA"; fine.blend_type = "MULTIPLY"; fine.inputs["Factor"].default_value = 0.35
lnk(gr.outputs[0], fine.inputs[6]); lnk(n2.outputs["Color"], fine.inputs[7])
mixg = nt.nodes.new("ShaderNodeMix"); mixg.data_type = "RGBA"; lnk(edge.outputs[0], mixg.inputs["Factor"])
lnk(pav.outputs["Color"], mixg.inputs[6]); lnk(fine.outputs[2], mixg.inputs[7]); lnk(mixg.outputs[2], p.inputs["Base Color"])
blades = gnode("ShaderNodeTexNoise", Scale=40.0, Detail=2.0); lnk(tc.outputs["Object"], blades.inputs["Vector"])
gb = nt.nodes.new("ShaderNodeMix"); gb.data_type = "FLOAT"; lnk(edge.outputs[0], gb.inputs["Factor"])
lnk(pav.outputs["Fac"], gb.inputs[2]); lnk(blades.outputs["Fac"], gb.inputs[3])
bump = gnode("ShaderNodeBump", Strength=0.35, Distance=0.02); lnk(gb.outputs[0], bump.inputs["Height"]); lnk(bump.outputs[0], p.inputs["Normal"])
lnk(p.outputs[0], out.inputs[0]); ground.data.materials.append(m)

import random
rnd = random.Random(7)
def simple_mat(name, color, rough=0.8, emit=None, strength=0.0):
    m, nt, out = node_mat(name)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Base Color"].default_value = (*color, 1); p.inputs["Roughness"].default_value = rough
    if emit:
        p.inputs["Emission Color"].default_value = (*emit, 1); p.inputs["Emission Strength"].default_value = strength
    nt.links.new(p.outputs[0], out.inputs[0]); return m

def leaves_mat(name, dark, light):
    """Foliage: clumps of leaves (light where they catch the sun, dark in the gaps), as colour and bump."""
    m, nt, out = node_mat(name)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Roughness"].default_value = 0.85
    tc = nt.nodes.new("ShaderNodeTexCoord")
    vor = nt.nodes.new("ShaderNodeTexVoronoi"); vor.inputs["Scale"].default_value = 1.6; nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
    nz_ = nt.nodes.new("ShaderNodeTexNoise"); nz_.inputs["Scale"].default_value = 6.0; nz_.inputs["Detail"].default_value = 10.0
    nt.links.new(tc.outputs["Object"], nz_.inputs["Vector"])
    mx = nt.nodes.new("ShaderNodeMath"); mx.operation = "MULTIPLY_ADD"
    nt.links.new(vor.outputs["Distance"], mx.inputs[0]); mx.inputs[1].default_value = 0.6; nt.links.new(nz_.outputs["Fac"], mx.inputs[2])
    cr = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(mx.outputs[0], cr.inputs[0])
    cr.color_ramp.elements[0].position = 0.55; cr.color_ramp.elements[0].color = (*dark, 1)
    cr.color_ramp.elements[1].position = 0.95; cr.color_ramp.elements[1].color = (*light, 1)
    nt.links.new(cr.outputs[0], p.inputs["Base Color"])
    try: p.inputs["Subsurface Weight"].default_value = 0.15; p.inputs["Subsurface Radius"].default_value = (0.3, 0.6, 0.2)
    except KeyError: pass
    bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.8; bp.inputs["Distance"].default_value = 0.15
    nt.links.new(mx.outputs[0], bp.inputs["Height"]); nt.links.new(bp.outputs[0], p.inputs["Normal"])
    nt.links.new(p.outputs[0], out.inputs[0]); return m

# trees: lumpy, leafy clumps at the sides of the plaza and a line behind the castle (the hub's and Fantasyland's)
LEAVES = [leaves_mat("leaves%d" % i, dk, lt) for i, (dk, lt) in enumerate((
    ((0.015, 0.035, 0.012), (0.10, 0.19, 0.05)), ((0.02, 0.045, 0.015), (0.13, 0.21, 0.06)), ((0.012, 0.03, 0.015), (0.08, 0.16, 0.06))))]
big = bpy.data.textures.new("lumps", "CLOUDS"); big.noise_scale = 0.35; big.noise_depth = 3
small = bpy.data.textures.new("twigs", "CLOUDS"); small.noise_scale = 0.08; small.noise_depth = 2
# a leaf cluster: a small, flattened lump; thousands per tree make the crown's texture
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.28, location=(0, 0, -500)); LEAF = bpy.context.active_object
LEAF.name = "leaf"; LEAF.scale = (1.0, 1.0, 0.45); LEAF.hide_render = True
def leaf_instance_mat():
    m, nt, out = node_mat("leafclusters")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Roughness"].default_value = 0.7
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    cr = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(oi.outputs["Random"], cr.inputs[0])
    cr.color_ramp.elements[0].color = (0.018, 0.045, 0.012, 1); cr.color_ramp.elements[1].color = (0.16, 0.26, 0.06, 1)
    nt.links.new(cr.outputs[0], p.inputs["Base Color"])
    try: p.inputs["Subsurface Weight"].default_value = 0.2; p.inputs["Subsurface Radius"].default_value = (0.2, 0.5, 0.1)
    except KeyError: pass
    nt.links.new(p.outputs[0], out.inputs[0]); return m
LEAF.data.materials.append(leaf_instance_mat())
def scatter(obj, inst, count, size, size_random=0.5, seed=0, align=False):
    """Scatter instances of inst over obj's faces: emitter particles born at frame 1 that stay put (hair
    particles would ignore the size and draw them at a few percent of it)."""
    ps = obj.modifiers.new("scatter", "PARTICLE_SYSTEM").particle_system; st = ps.settings
    st.type = "EMITTER"; st.count = count; st.frame_start = st.frame_end = 1; st.lifetime = 100000
    st.emit_from = "FACE"; st.use_emit_random = True; st.physics_type = "NO"; st.normal_factor = 0.0
    st.render_type = "OBJECT"; st.instance_object = inst; st.particle_size = size; st.size_random = size_random
    if align: st.use_rotations = True; st.rotation_mode = "NOR"; st.phase_factor_random = 2.0; st.rotation_factor_random = 0.6
    ps.seed = seed; return ps
def leafy(t, r, size=1.0):
    return scatter(t, LEAF, int(r * r * 70), size, 0.6, rnd.randrange(1000), align=True)
def tree(x, y, r):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=r, location=(x, y, r * 0.95))
    t = bpy.context.active_object; t.scale.z = rnd.uniform(0.9, 1.3)
    d = t.modifiers.new("lumps", "DISPLACE"); d.texture = big; d.strength = r * 0.55; d.texture_coords = "GLOBAL"
    d2 = t.modifiers.new("twigs", "DISPLACE"); d2.texture = small; d2.strength = 0.45; d2.texture_coords = "GLOBAL"
    bpy.ops.object.shade_smooth()
    t.data.materials.append(rnd.choice(LEAVES)); leafy(t, r); return t
# the hub, as in the photos: paving everywhere, a walkway straight to the castle, mown lawn either
# side edged with low clipped hedges and flower beds, and only a few shaped trees, off to the sides
def lawn_mat():
    m, nt, out = node_mat("lawn")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Roughness"].default_value = 0.75
    tc = nt.nodes.new("ShaderNodeTexCoord"); sx = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(tc.outputs["Object"], sx.inputs[0])
    stripe = nt.nodes.new("ShaderNodeMath"); stripe.operation = "SINE"
    k = nt.nodes.new("ShaderNodeMath"); k.operation = "MULTIPLY"; nt.links.new(sx.outputs["X"], k.inputs[0]); k.inputs[1].default_value = math.pi / 2.5
    nt.links.new(k.outputs[0], stripe.inputs[0])                                       # mowing stripes, 2.5 m wide
    st = nt.nodes.new("ShaderNodeMath"); st.operation = "GREATER_THAN"; nt.links.new(stripe.outputs[0], st.inputs[0]); st.inputs[1].default_value = 0
    nz_ = nt.nodes.new("ShaderNodeTexNoise"); nz_.inputs["Scale"].default_value = 3.0; nz_.inputs["Detail"].default_value = 8.0
    nt.links.new(tc.outputs["Object"], nz_.inputs["Vector"])
    mx = nt.nodes.new("ShaderNodeMath"); mx.operation = "MULTIPLY_ADD"; nt.links.new(st.outputs[0], mx.inputs[0]); mx.inputs[1].default_value = 0.25
    nt.links.new(nz_.outputs["Fac"], mx.inputs[2])
    cr = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(mx.outputs[0], cr.inputs[0])
    cr.color_ramp.elements[0].position = 0.3; cr.color_ramp.elements[0].color = (0.07, 0.17, 0.035, 1)
    cr.color_ramp.elements[1].position = 0.9; cr.color_ramp.elements[1].color = (0.15, 0.30, 0.06, 1)
    nt.links.new(cr.outputs[0], p.inputs["Base Color"])
    fine = nt.nodes.new("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 120.0; nt.links.new(tc.outputs["Object"], fine.inputs["Vector"])
    bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.3; nt.links.new(fine.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs[0], p.inputs["Normal"]); nt.links.new(p.outputs[0], out.inputs[0]); return m
LAWN = lawn_mat()
hedge_mat = leaves_mat("hedge", (0.012, 0.035, 0.012), (0.08, 0.17, 0.05))
def flowers_mat():
    m, nt, out = node_mat("flowers")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled"); p.inputs["Roughness"].default_value = 0.6
    oi = nt.nodes.new("ShaderNodeObjectInfo"); cr = nt.nodes.new("ShaderNodeValToRGB"); cr.color_ramp.interpolation = "CONSTANT"
    nt.links.new(oi.outputs["Random"], cr.inputs[0])
    for i, (pos, c) in enumerate(((0.0, (0.75, 0.05, 0.12)), (0.3, (0.95, 0.35, 0.55)), (0.55, (0.95, 0.75, 0.1)), (0.8, (0.92, 0.9, 0.85)))):
        e = cr.color_ramp.elements[i] if i < 2 else cr.color_ramp.elements.new(pos); e.position = pos; e.color = (*c, 1)
    nt.links.new(cr.outputs[0], p.inputs["Base Color"]); nt.links.new(p.outputs[0], out.inputs[0]); return m
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.16, location=(0, 0, -600)); BLOOM = bpy.context.active_object
BLOOM.hide_render = True; BLOOM.data.materials.append(flowers_mat())

def box(x0, x1, y0, y1, z, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=((x0 + x1) / 2, (y0 + y1) / 2, z / 2)); o = bpy.context.active_object
    o.scale = ((x1 - x0) / 2, (y1 - y0) / 2, z / 2); bpy.ops.object.transform_apply(scale=True)
    if bevel: bv = o.modifiers.new("round", "BEVEL"); bv.width = bevel; bv.segments = 3
    o.data.materials.append(mat); return o
WALK = 9.0                                                     # the walkway's half-width
for side in (-1, 1):
    x0, x1 = side * WALK, side * 120
    xa, xb = min(x0, x1), max(x0, x1)
    # the lawn patch (a slab a hand's height up, so its edge reads), then a hedge along its walkway edge
    # and a flower bed in front of that
    lawn = box(xa, xb, -168, -50, 0.06, LAWN)
    edge = side * (WALK + 0.6)
    h = box(min(edge, edge + side * 0.9), max(edge, edge + side * 0.9), -160, -54, 0.85, hedge_mat, 0.25)
    leafy(h, 0.6, 0.5).settings.count = 2500
    bed = box(min(edge + side * 0.9, edge + side * 4.4), max(edge + side * 0.9, edge + side * 4.4), -160, -54, 0.25, hedge_mat)
    scatter(bed, BLOOM, 26000, 1.0, 0.5, 11 + side)
    # a low hedge along the lawn's far edge too, towards the castle
    h2 = box(xa, xb, -51.2, -50.2, 0.85, hedge_mat, 0.25); leafy(h2, 0.6, 0.5).settings.count = 2500
# a few shaped trees: on the lawns' outer parts and off the castle's flanks
# the flower circle on the walkway in front of the castle (where the Partners statue's is, in the hub)
bpy.ops.mesh.primitive_cylinder_add(radius=6.5, depth=0.5, location=(0, -92, 0.25), vertices=64); circ = bpy.context.active_object
circ.data.materials.append(hedge_mat)
scatter(circ, BLOOM, 30000, 1.0, 0.5, 21)
# its stone kerb: a ring, not a lid (the flowers show over it)
bpy.ops.mesh.primitive_torus_add(major_radius=6.65, minor_radius=0.22, location=(0, -92, 0.32), major_segments=96, minor_segments=12)
rim = bpy.context.active_object; rim.scale = (1, 1, 1.4); rim.data.materials.append(simple_mat("rim", (0.55, 0.52, 0.47), 0.8))
for x, y, r in ((-62, -120, 3.4), (-95, -90, 4.0), (70, -125, 3.6), (100, -95, 4.2)):
    tree(x, y, r)
# and the hub's edges: trees flanking the castle and closing the view at the sides (not on the plaza)
for side in (-1, 1):
    # (the camera sees ~80 m either side at the castle: they go there, staggered back into the distance)
    for i in range(18):
        x = side * rnd.uniform(50, 100); y = rnd.uniform(-30, 150)
        if abs(x) < 62 and y < 15: continue                     # (keep the castle's front corners clear)
        tree(x, y, rnd.uniform(4.0, 7.5))

# ---- the hub's garden details (the reference photo): spiral topiaries, low black iron railings
# around the beds and the flower circle, and rounded shrubs along the foot of the forecourt walls
iron = simple_mat("iron", (0.02, 0.02, 0.025), 0.35)
def railing(points, height=0.75, pitch=0.16):
    """A low wrought-iron railing along a polyline [(x, y), ...]: two rails and close-set bars."""
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        dx, dy = xb - xa, yb - ya; L_ = math.hypot(dx, dy); ang = math.atan2(dy, dx)
        for z in (0.12, height):
            bpy.ops.mesh.primitive_cylinder_add(radius=0.022, depth=L_, location=((xa + xb) / 2, (ya + yb) / 2, z), vertices=6)
            r_ = bpy.context.active_object; r_.rotation_euler = (0, math.radians(90), ang); r_.data.materials.append(iron)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=height, location=(xa, ya, height / 2), vertices=5)
        bar = bpy.context.active_object; bar.data.materials.append(iron)
        ar = bar.modifiers.new("bars", "ARRAY"); ar.count = max(2, int(L_ / pitch)); ar.use_relative_offset = False
        ar.use_constant_offset = True; ar.constant_offset_displace = (pitch * math.cos(ang), pitch * math.sin(ang), 0)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.05, location=(xa, ya, height + 0.05), segments=8, ring_count=6)   # a finial at each post
        bpy.context.active_object.data.materials.append(iron)
def topiary(x, y, h=2.6):
    """A spiral topiary: a tight helix of leafy lumps winding up a narrowing cone."""
    turns, n = 3.2, 44
    for k in range(n):
        u = k / (n - 1); a = u * turns * 2 * math.pi; rr_ = 0.42 * (1 - 0.75 * u) + 0.06
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.30 * (1 - 0.55 * u) + 0.08,
                                              location=(x + rr_ * math.cos(a), y + rr_ * math.sin(a), 0.35 + u * h))
        b = bpy.context.active_object; bpy.ops.object.shade_smooth(); b.data.materials.append(hedge_mat)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.35, location=(x, y, 0.17), vertices=12)   # its pot
    bpy.context.active_object.data.materials.append(simple_mat("pot", (0.45, 0.42, 0.38), 0.8))
def shrub(x, y, r):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r, location=(x, y, r * 0.7))
    t = bpy.context.active_object; t.scale.z = 0.8
    d = t.modifiers.new("lumps", "DISPLACE"); d.texture = big; d.strength = r * 0.3; d.texture_coords = "GLOBAL"
    bpy.ops.object.shade_smooth(); t.data.materials.append(rnd.choice(LEAVES)); leafy(t, r * 1.4); return t
for side in (-1, 1):
    # railings along the beds beside the walkway, and across the lawns' far ends
    xe = side * (WALK + 0.35)
    railing([(xe, -160), (xe, -54)])
    railing([(xe, -54), (side * 40, -54)])
    # spiral topiaries in pairs along the walkway, and at the forecourt's corners
    for y in (-140, -112, -84, -60):
        topiary(side * (WALK + 2.4), y)
    for x in (12, 22, 30):
        topiary(side * x, -44, 3.0)
    # rounded shrubs along the foot of the forecourt walls
    for x in range(8, 36, 3):
        shrub(side * (x + rnd.uniform(-0.6, 0.6)), -41.5 + rnd.uniform(-0.5, 0.5), rnd.uniform(0.7, 1.1))
# a railing around the flower circle
railing([(7.1 * math.cos(a), -92 + 7.1 * math.sin(a)) for a in [k * 2 * math.pi / 48 for k in range(49)]], 0.6, 0.14)

# lamp posts along the plaza's front edge, Main Street style: a fluted post, a crossbar, three globes
NIGHT = LOOK == "night"; LIT = LOOK in ("night", "dusk")      # dusk: the lights coming on
post = simple_mat("post", (0.045, 0.04, 0.035), 0.45)
trim = simple_mat("trim", (0.55, 0.42, 0.18), 0.35)
globe = simple_mat("globe", (0.92, 0.9, 0.84), 0.25, emit=(1.0, 0.74, 0.42), strength=45.0 if NIGHT else 14.0 if LIT else 0.0)
LAMPS = [(x, -58 + 0.004 * x * x) for x in (-44, -32, -20, 20, 32, 44)]
GLOBES = []
def part(op, mat, **kw):
    op(**kw); o = bpy.context.active_object; o.data.materials.append(mat); bpy.ops.object.shade_smooth(); return o
for x, y in LAMPS:
    part(bpy.ops.mesh.primitive_cylinder_add, post, radius=0.32, depth=0.7, location=(x, y, 0.35), vertices=16)          # base
    part(bpy.ops.mesh.primitive_cone_add, post, radius1=0.16, radius2=0.08, depth=3.6, location=(x, y, 2.4), vertices=12)  # post
    part(bpy.ops.mesh.primitive_torus_add, trim, major_radius=0.12, minor_radius=0.03, location=(x, y, 1.1))
    bar = part(bpy.ops.mesh.primitive_cylinder_add, post, radius=0.04, depth=1.4, location=(x, y, 3.9), vertices=8)
    bar.rotation_euler = (0, math.radians(90), 0)
    for gx, gz in ((-0.7, 3.95), (0.7, 3.95), (0.0, 4.55)):
        part(bpy.ops.mesh.primitive_uv_sphere_add, globe, radius=0.26, location=(x + gx, y, gz + 0.2), segments=16, ring_count=10)
        part(bpy.ops.mesh.primitive_cone_add, trim, radius1=0.14, radius2=0.04, depth=0.18, location=(x + gx, y, gz + 0.52), vertices=10)
        GLOBES.append((x + gx, y, gz + 0.2))

# ------------------------------------------------------------------ world + light
world = bpy.data.worlds.new("World"); scn.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wn.clear()
wout = wn.new("ShaderNodeOutputWorld"); bg = wn.new("ShaderNodeBackground"); world.node_tree.links.new(bg.outputs[0], wout.inputs[0])
HDRI_DIR = os.environ.get("HDRI_DIR", os.path.join(REPO, "assets", "hdri"))
SKIES = {"day": ("kloofendal_48d_partly_cloudy_puresky", float(arg("--rot", "120")), float(arg("--exp", "-0.75"))),
}
EXPOSURE = 0.0
if LOOK in SKIES:
    name, rot, EXPOSURE = SKIES[LOOK]
    tex = wn.new("ShaderNodeTexEnvironment"); tex.image = bpy.data.images.load(os.path.join(HDRI_DIR, name + ".hdr"))
    tc = wn.new("ShaderNodeTexCoord"); mp = wn.new("ShaderNodeMapping"); mp.inputs["Rotation"].default_value = (0, 0, math.radians(rot))
    world.node_tree.links.new(tc.outputs["Generated"], mp.inputs[0]); world.node_tree.links.new(mp.outputs[0], tex.inputs["Vector"])
    world.node_tree.links.new(tex.outputs[0], bg.inputs[0])
else:
    tcw = wn.new("ShaderNodeTexCoord"); sz = wn.new("ShaderNodeSeparateXYZ"); world.node_tree.links.new(tcw.outputs["Generated"], sz.inputs[0])
    grd = wn.new("ShaderNodeValToRGB"); world.node_tree.links.new(sz.outputs["Z"], grd.inputs[0])
    if LOOK == "dusk":      # blue hour: a warm glow low down, deep blue above
        grd.color_ramp.elements[0].position = 0.0; grd.color_ramp.elements[0].color = (0.55, 0.30, 0.20, 1)
        mid = grd.color_ramp.elements.new(0.12); mid.color = (0.12, 0.15, 0.32, 1)
        grd.color_ramp.elements[2 if len(grd.color_ramp.elements) > 2 else 1].position = 0.55
        grd.color_ramp.elements[-1].color = (0.025, 0.045, 0.13, 1)
    else:                   # night: navy overhead, lighter towards the horizon
        grd.color_ramp.elements[0].position = 0.0; grd.color_ramp.elements[0].color = (0.035, 0.06, 0.14, 1)
        grd.color_ramp.elements[1].position = 0.45; grd.color_ramp.elements[1].color = (0.006, 0.012, 0.035, 1)
    world.node_tree.links.new(grd.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = float(arg("--sky", "1.0"))
if LOOK == "day":
    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(42), 0, math.radians(-35)))   # from the front left, mid-morning
    sun = bpy.context.active_object; sun.data.energy = float(arg("--sun", "3.0")); sun.data.angle = math.radians(1.0)

def spot(at, aim, color, power, size_deg, blend=0.6):
    bpy.ops.object.light_add(type="SPOT", location=at); l = bpy.context.active_object
    l.data.energy = power; l.data.color = color; l.data.spot_size = math.radians(size_deg); l.data.spot_blend = blend
    l.rotation_euler = (Vector(aim) - Vector(at)).to_track_quat("-Z", "Y").to_euler(); return l
if LIT:
    # the castle at night (the reference photos): blue floodlight across the front from the ground,
    # magenta-pink on the centre tower, warm light in the archway, a faint moon for the outline
    K = float(arg("--flood", "1.0" if NIGHT else "0.3"))
    BLUE_L, PINK_L = (0.06, 0.16, 1.0), (1.0, 0.16, 0.62)
    # the forecourt's face, from the plaza floor
    for x in (-30, -15, 0, 15, 30):
        spot((x * 1.2, -40, 0.4), (x * 0.9, -6, 9), BLUE_L, 30000 * K, 60)
    # the towers, from fittings on the forecourt terrace (the terrace hides them from the plaza)
    # (the front wall is ~39 m in front of the middle: anything closer would be inside the castle)
    for x in (-6, 6):
        spot((x * 4, -110, 16), (x * 0.3, 6, 34), PINK_L, 450000 * K, 7, 0.7)   # the centre tower, magenta-pink
    for x in (-25, 25):
        spot((x, -90, 12), (x * 0.4, 0, 20), BLUE_L, 300000 * K, 22, 0.8)     # the gables and bastions
    # and from far off in the plaza, high up: the upper castle and the spire
    for x in (-40, 40):
        spot((x, -130, 22), (0, 4, 40), BLUE_L, 500000 * K, 14, 0.8)
    bpy.ops.object.light_add(type="POINT", location=(2.5, -12, 3)); w = bpy.context.active_object
    w.data.energy = 3000 * K; w.data.color = (1.0, 0.62, 0.28)                   # the archway
    for g in GLOBES:
        bpy.ops.object.light_add(type="POINT", location=g); l = bpy.context.active_object
        l.data.energy = 150 * K; l.data.color = (1.0, 0.7, 0.36); l.data.shadow_soft_size = 0.25
    if NIGHT:
        # moonlight: from high on the right, behind the castle (the moon's in the picture), plus a soft cool
        # fill from the front so the trees and lawn aren't black
        bpy.ops.object.light_add(type="SUN", rotation=(math.radians(-40), math.radians(25), 0))
        moon = bpy.context.active_object; moon.data.energy = 0.35; moon.data.color = (0.62, 0.72, 1.0); moon.data.angle = math.radians(0.6)
        bpy.ops.object.light_add(type="SUN", rotation=(math.radians(60), 0, math.radians(-20)))
        fill = bpy.context.active_object; fill.data.energy = float(arg("--fill", "0.12")); fill.data.color = (0.55, 0.65, 1.0)

# ------------------------------------------------------------------ camera: from the hub, looking up a little
bpy.ops.object.camera_add(); cam = bpy.context.active_object; scn.camera = cam
cam.data.lens = float(arg("--lens", "36")); cam.data.clip_end = 5000
cam.data.shift_x = float(arg("--shift-x", "-0.14"))         # the castle right of centre: the cards go left
cam.data.shift_y = float(arg("--shift", "0.18"))            # more sky, same perspective
DIST, EYE = float(arg("--dist", "140")), float(arg("--eye", "1.8"))
target = Vector((0, 0, float(arg("--look-at", "18"))))
cam.location = Vector((0, -DIST, EYE))
cam.rotation_euler = (Vector((0, 0, EYE + (target.z - EYE) * 0.35)) - cam.location).to_track_quat("-Z", "Y").to_euler()

if NIGHT:
    bpy.context.view_layer.update()
    MOON = (float(arg("--moon-x", "0.86")), float(arg("--moon-y", "0.84")))   # where on screen (0..1, from the bottom left)
    fr = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scn)]      # the frame's corners at distance 1 (TR, BR, BL, TL)
    tr, br, bl, tl = fr
    pt = bl + (br - bl) * MOON[0] + (tl - bl) * MOON[1]
    d = (pt - cam.location).normalized(); far = 3000.0
    bpy.ops.mesh.primitive_uv_sphere_add(radius=far * math.tan(math.radians(0.85)), location=cam.location + d * far, segments=48, ring_count=24)
    mo = bpy.context.active_object; mo.name = "moon"
    m, nt, out = node_mat("moon")
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = 6.0
    nz_ = nt.nodes.new("ShaderNodeTexNoise"); nz_.inputs["Scale"].default_value = 3.0; nz_.inputs["Detail"].default_value = 6.0
    cr = nt.nodes.new("ShaderNodeValToRGB"); nt.links.new(nz_.outputs["Fac"], cr.inputs[0])
    cr.color_ramp.elements[0].position = 0.45; cr.color_ramp.elements[0].color = (0.62, 0.64, 0.66, 1)       # the seas
    cr.color_ramp.elements[1].position = 0.6; cr.color_ramp.elements[1].color = (0.95, 0.95, 0.92, 1)
    nt.links.new(cr.outputs[0], em.inputs["Color"]); nt.links.new(em.outputs[0], out.inputs[0]); mo.data.materials.append(m)
    mo.visible_shadow = False
    print("moon at", [round(v, 2) for v in MOON])

# ------------------------------------------------------------------ render
scn.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"; prefs.get_devices()
    for dv in prefs.devices: dv.use = True
    scn.cycles.device = "GPU"
except Exception as e:
    print("GPU unavailable:", e)
scn.cycles.samples = SAMPLES; scn.cycles.use_denoising = True
scn.render.resolution_x, scn.render.resolution_y = W * RES, H * RES; scn.render.resolution_percentage = 100
scn.view_settings.view_transform = "AgX"; scn.view_settings.exposure = EXPOSURE
for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast"):
    try: scn.view_settings.look = look; break
    except TypeError: pass
if WINDOWS_LOOK:
    for o in scn.objects:
        if o.type == "MESH" and o not in (castle,) and o.data.materials:
            for i in range(len(o.data.materials)): o.data.materials[i] = bpy.data.materials["black"]
    bg.inputs[1].default_value = 0.0; scn.cycles.samples = 16; scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"; scn.view_settings.exposure = 0.0
if LOOK == "keep":
    # what the AI detail pass must leave exactly as rendered (ai_detail.py --keep): the castle and the
    # lamp posts, white where they're seen, everything else black (and still in front of them)
    km, knt, kout = node_mat("keepwhite"); ke = knt.nodes.new("ShaderNodeEmission"); ke.inputs["Color"].default_value = (1, 1, 1, 1)
    knt.links.new(ke.outputs[0], kout.inputs[0])
    hm, hnt, hout = node_mat("cutout"); hb = hnt.nodes.new("ShaderNodeHoldout"); hnt.links.new(hb.outputs[0], hout.inputs[0])
    keep_mats = {"castle", "windowglass", "post", "trim", "globe"}
    for o in scn.objects:
        if o.type == "MESH" and o.data.materials:
            for i, mt in enumerate(o.data.materials):
                o.data.materials[i] = km if (o is castle or (mt and mt.name.split(".")[0] in keep_mats)) else hm
    bg.inputs[1].default_value = 0.0; scn.cycles.samples = 16; scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"; scn.view_settings.exposure = 0.0
if LOOK == "mask":
    # where the device's fireworks mustn't draw: everything that isn't sky (castle, trees, lamps)
    ground.hide_render = True; scn.render.film_transparent = True; scn.render.image_settings.color_mode = "RGBA"
scn.render.image_settings.file_format = "PNG"
scn.render.filepath = os.path.join(OUT, LOOK + ".png")
if "--count" in argv:                   # (debugging: how many leaf clusters, blooms... actually reach the renderer)
    import collections
    dg = bpy.context.evaluated_depsgraph_get(); cnt = collections.Counter()
    for inst in dg.object_instances:
        if inst.is_instance:
            cnt[inst.object.name] += 1
            if cnt[inst.object.name] in (1, 5000):
                m_ = inst.matrix_world; print("  e.g.", inst.object.name, "from", inst.parent.name if inst.parent else "?",
                      "at", tuple(round(v, 2) for v in m_.translation), "scale", tuple(round(v, 3) for v in m_.to_scale()))
    print("instances", dict(cnt))
elif "--info" not in argv:
    bpy.ops.render.render(write_still=True)

# where things land on screen (for the device's scene.json)
bpy.context.view_layer.update()
def px(v):
    c = world_to_camera_view(scn, cam, v); return [round(c.x * W, 1), round((1 - c.y) * H, 1)]
vs = [castle.matrix_world @ v.co for v in castle.data.vertices]
top = max(vs, key=lambda v: v.z)
pos = {"spire": px(top), "base_left": px(Vector((min(v.x for v in vs), 0, 0))), "base_right": px(Vector((max(v.x for v in vs), 0, 0))),
       "horizon": px(Vector((0, 2000, 0)))[1]}
json.dump(pos, open(os.path.join(WORK, "positions.json"), "w"), indent=1)
print("positions", pos)
