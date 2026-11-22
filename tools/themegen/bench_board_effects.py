"""Second half of the board speed test (bench_board.py runs out of memory on the 32 MB Nano before it
gets here): small effects, packing pixels and writing to the framebuffer. Needs /root/day.png."""
import functools, mmap, os, random, time
print = functools.partial(print, flush=True)
from PIL import Image, ImageChops, ImageDraw
W, H, HZ = 800, 480, 196
def bench(name, fn, n=5):
    fn(); t = time.perf_counter()
    for _ in range(n): fn()
    ms = (time.perf_counter() - t) / n * 1000; print("%-50s %8.1f ms (%5.1f fps)" % (name, ms, 1000 / ms))
day = Image.open("/root/day.png").convert("RGB")
reg = day.crop((40, 260, 340, 460))
def foam():
    lay = Image.new("RGBA", reg.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for _ in range(150):
        x, y = random.uniform(0, 300), random.uniform(0, 200); d.ellipse((x, y, x + 3, y + 1.6), fill=(245, 245, 250, 120))
    return Image.alpha_composite(reg.convert("RGBA"), lay)
bench("foam: 150 dots on 300x200 + composite", foam)
puff = Image.new("RGBA", (40, 40), (140, 134, 128, 0)); ImageDraw.Draw(puff).ellipse((4, 4, 36, 36), fill=(140, 134, 128, 50))
sky = day.crop((150, 100, 450, 300))
def smoke():
    for _ in range(60): sky.paste(puff, (random.randrange(0, 260), random.randrange(0, 160)), puff)
bench("smoke: 60 puffs pasted with alpha", smoke)
skyf = day.crop((0, 0, W, HZ))
def fw():
    lay = Image.new("RGB", skyf.size); d = ImageDraw.Draw(lay)
    for _ in range(220):
        x, y = random.uniform(100, 700), random.uniform(20, 180); d.line((x, y, x + 3, y + 2), fill=(255, 200, 120))
    return ImageChops.add(skyf, lay)
bench("fireworks: 220 sparks + additive (sky 800x196)", fw)
small = day.crop((300, 100, 360, 140))
bench("one 60x40 sprite pasted", lambda: day.paste(small, (10, 10)), 50)
bench("pack full frame to BGRX", lambda: day.tobytes("raw", "BGRX"))
water = day.crop((0, HZ, W, H))
bench("pack water region to BGRX", lambda: water.tobytes("raw", "BGRX"))
bench("pack 60x40 to BGRX", lambda: small.tobytes("raw", "BGRX"), 50)
fd = os.open("/dev/fb0", os.O_RDWR); mem = mmap.mmap(fd, W * H * 4, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
data = day.tobytes("raw", "BGRX"); del day
wd = water.tobytes("raw", "BGRX")
def full(): mem[0:len(data)] = data
def wat(): o = HZ * W * 4; mem[o:o + len(wd)] = wd
bench("copy full frame into framebuffer", full)
bench("copy water region into framebuffer", wat)
del data
raw = water.tobytes(); del water
bench("water frame from raw bytes (frombytes)", lambda: Image.frombytes("RGB", (W, H - HZ), raw))
f = open("/root/w.raw", "wb"); f.write(wd); f.close()
def rd():
    with open("/root/w.raw", "rb") as g: g.readinto(memoryview(mem)[HZ * W * 4:HZ * W * 4 + len(wd)])
bench("read a water frame from SD straight into fb", rd)
os.remove("/root/w.raw")
