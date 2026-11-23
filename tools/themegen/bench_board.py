"""Speed test for the vacation countdown on the board: times each piece of a frame
using Pillow only (the image has no numpy), the way the device app would do it.

    tools/push_to_board.py vacation/modules/cruise/scenes/dream/day.png /root/day.png
    tools/push_to_board.py tools/themegen/bench_board.py /root/bench_board.py
    app stop; python3 /root/bench_board.py; app start

Draws to /dev/fb0 for the framebuffer test (the screen shows test frames for a few seconds)."""
import functools, math, mmap, os, random, time
print = functools.partial(print, flush=True)      # keep results even if the run dies part way
from PIL import Image, ImageChops, ImageDraw

W, H, HORIZON = 800, 480, 196
WH = H - HORIZON                     # rows of water
random.seed(1)

def rss():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"): return line.split()[1] + " kB"

def bench(name, fn, n=10):
    fn()                                   # warm up
    t = time.perf_counter()
    for _ in range(n): fn()
    ms = (time.perf_counter() - t) / n * 1000
    print("%-52s %8.1f ms  (%5.1f fps)" % (name, ms, 1000 / ms if ms else 0))
    return ms

print("start", rss())
t = time.perf_counter(); day = Image.open("/root/day.png").convert("RGB"); print("decode day.png  %.0f ms" % ((time.perf_counter() - t) * 1000), rss())
# stand-ins for the other plates (same size; content doesn't change the timings). Only two full plates
# are held: the 32 MB Nano runs out of memory with four (Pillow keeps RGB at 4 bytes a pixel, 1.5 MB each)
night = Image.eval(day, lambda v: v // 5)
dusk = night; lit = day
ship = Image.new("L", (W, H), 0); ImageDraw.Draw(ship).polygon([(60, 330), (120, 250), (380, 220), (690, 300), (690, 375), (60, 345)], fill=255)
print("plates loaded", rss())

print("\n-- time of day (runs only when the light changes, e.g. once every few seconds)")
if not os.environ.get("SKIP_MESH"):
    bench("blend two plates, full frame", lambda: Image.blend(day, dusk, 0.3), 3)
    bench("blend three plates (day/dusk/night)", lambda: Image.blend(Image.blend(day, dusk, 0.3), night, 0.2), 3)

print("\n-- window lights: switch one 4x3 cell (paste from the lit plate)")
cells = [(random.randrange(100, 680) // 4 * 4, random.randrange(200, 290) // 3 * 3) for _ in range(50)]
frame = day.copy()
def cells_on():
    for (x, y) in cells: frame.paste(lit.crop((x, y, x + 4, y + 3)), (x, y))
ms = bench("50 cells switched", cells_on)
print("   -> %.2f ms per cell" % (ms / 50))
def cell_fade():
    for (x, y) in cells:
        b = (x, y, x + 4, y + 3); frame.paste(Image.blend(night.crop(b), lit.crop(b), 0.5), (x, y))
bench("50 cells mid-fade (blend)", cell_fade)

print("\n-- water: displace the %d rows below the horizon, then put the ship back over it" % WH)
src = day.crop((0, HORIZON, W, H)); shipw = ship.crop((0, HORIZON, W, H))
out = Image.new("RGB", (W, WH))
def rows_shift(band):
    def run(t=[0.0]):
        t[0] += 0.033
        for y in range(0, WH, band):
            amp = 0.35 + 2.4 * y / WH
            dx = int(round(amp * math.sin(y * 0.37 + t[0] * 2.3)))
            out.paste(src.crop((0, y, W, y + band)), (dx, y))
    return run
bench("A. shift each row whole pixels (crop+paste x284)", rows_shift(1))
bench("A. shift 2-row bands (x142)", rows_shift(2))
bench("A. shift 4-row bands (x71)", rows_shift(4))

def mesh(cols, rows, resample):
    cw, rh = W / cols, WH / rows
    def run(t=[0.0]):
        t[0] += 0.033; m = []
        for j in range(rows):
            y0, y1 = j * rh, (j + 1) * rh
            amp = 0.35 + 2.4 * y0 / WH
            for i in range(cols):
                x0, x1 = i * cw, (i + 1) * cw
                def d(x, y): return amp * math.sin(y * 0.37 + t[0] * 2.3 + x * 0.021), 0.45 * amp * math.sin(y * 0.11 - t[0] * 1.6 + x * 0.013)
                (a, b), (c, e), (f, g), (h, k) = d(x0, y0), d(x0, y1), d(x1, y1), d(x1, y0)
                m.append(((int(x0), int(y0), int(x1), int(y1)),
                          (x0 + a, y0 + b, x0 + c, y1 + e, x1 + f, y1 + g, x1 + h, y0 + k)))
        return src.transform((W, WH), Image.Transform.MESH, m, resample)
    return run
if not os.environ.get("SKIP_MESH"):      # slow (seconds) and memory-hungry on the board: SKIP_MESH=1 leaves them out
    bench("B. mesh warp 16x36 quads, nearest", mesh(16, 36, Image.Resampling.NEAREST), 3)
    bench("B. mesh warp 16x36 quads, bilinear (sub-pixel)", mesh(16, 36, Image.Resampling.BILINEAR), 3)
bench("put the ship back over the water (paste with mask)", lambda: out.paste(src, (0, 0), shipw))

print("\n-- C. pre-rendered water loop instead (memory, not speed)")
fb = WH * W * 4
print("   one water frame at 32 bpp = %d kB; 24 frames = %.1f MB; 48 = %.1f MB" % (fb // 1024, 24 * fb / 2**20, 48 * fb / 2**20))
raw = src.tobytes()
bench("   frame from raw bytes (frombytes)", lambda: Image.frombytes("RGB", (W, WH), raw))

print("\n-- small effects (on a 300x200 region)")
reg = day.crop((40, 260, 340, 460))
def foam():
    lay = Image.new("RGBA", reg.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for _ in range(150):
        x, y = random.uniform(0, 300), random.uniform(0, 200); d.ellipse((x, y, x + 3, y + 1.6), fill=(245, 245, 250, 120))
    return Image.alpha_composite(reg.convert("RGBA"), lay)
bench("foam: 150 dots on a layer + composite", foam)
puff = Image.new("RGBA", (40, 40), (140, 134, 128, 0)); ImageDraw.Draw(puff).ellipse((4, 4, 36, 36), fill=(140, 134, 128, 50))
sky = day.crop((150, 100, 450, 300))
def smoke():
    for _ in range(60): sky.paste(puff, (random.randrange(0, 260), random.randrange(0, 160)), puff)
bench("smoke: 60 puffs pasted with alpha", smoke)
skyfull = day.crop((0, 0, W, HORIZON))
def fireworks():
    lay = Image.new("RGB", skyfull.size); d = ImageDraw.Draw(lay)
    for _ in range(220):
        x, y = random.uniform(100, 700), random.uniform(20, 180); d.line((x, y, x + 3, y + 2), fill=(255, 200, 120), width=1)
    return ImageChops.add(skyfull, lay)
bench("fireworks: 220 sparks + additive blend (sky)", fireworks)

print("\n-- to the screen")
frame = day.copy()
bench("pack full frame to BGRX", lambda: frame.tobytes("raw", "BGRX"))
bench("pack water region to BGRX", lambda: out.tobytes("raw", "BGRX"))
fd = os.open("/dev/fb0", os.O_RDWR); mem = mmap.mmap(fd, W * H * 4, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
data = frame.tobytes("raw", "BGRX"); wdata = out.tobytes("raw", "BGRX")
def write_full(): mem[0:len(data)] = data
def write_water(): mem[HORIZON * W * 4:HORIZON * W * 4 + len(wdata)] = wdata
bench("copy full frame into the framebuffer", write_full)
bench("copy water region into the framebuffer", write_water)

print("\n-- a whole water frame: mesh warp 16x36 bilinear + ship + pack + copy")
warp = mesh(16, 36, Image.Resampling.BILINEAR)
def whole():
    w = warp(); w.paste(src, (0, 0), shipw)
    b = w.tobytes("raw", "BGRX"); mem[HORIZON * W * 4:HORIZON * W * 4 + len(b)] = b
if not os.environ.get("SKIP_MESH"): bench("whole water frame", whole, 3)
warp4 = rows_shift(4)
def whole4():
    warp4(); out.paste(src, (0, 0), shipw)
    b = out.tobytes("raw", "BGRX"); mem[HORIZON * W * 4:HORIZON * W * 4 + len(b)] = b
bench("whole water frame, 4-row bands instead", whole4, 20)
print("\nend", rss())
