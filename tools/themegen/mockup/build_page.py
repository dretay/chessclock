"""Turn the Blender renders into the theme's plates, and build the mockup page and a preview sheet.

  THEME_WORK/renders/<look>.png   (2x size, from scene.py)   ->  apps/cruise/scenes/dream/<look>.png (800x480)
  template.html + plates + the panel photo                     ->  THEME_WORK/mockup/cruise-mockups.html
                                                                    THEME_WORK/mockup/preview.png

The plates get the same light contrast and colour lift the mockup shows. The page embeds
everything (including the copyrighted photo), so it stays in work/ and out of git."""
import base64, io, json, os, shutil
from PIL import Image, ImageEnhance, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ASSETS = os.environ.get("THEME_ASSETS", os.path.join(REPO, "assets", "dream"))
WORK = os.environ.get("THEME_WORK", os.path.join(REPO, "tools", "themegen", "work", "dream"))
THEME = os.environ.get("THEME_OUT", os.path.join(REPO, "apps", "cruise", "scenes", "dream-blender"))
REN, MOCK = os.path.join(WORK, "renders"), os.path.join(WORK, "mockup")
os.makedirs(THEME, exist_ok=True); os.makedirs(MOCK, exist_ok=True)
W, H = 800, 480

# ---- the plates
for n in ("day", "dusk", "night_dark", "night_lit"):
    im = Image.open(os.path.join(REN, n + ".png")).convert("RGB").resize((W, H), Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.06); im = ImageEnhance.Color(im).enhance(1.12)
    im.save(os.path.join(THEME, n + ".png"), optimize=True)
(Image.open(os.path.join(REN, "mask.png")).getchannel("A").resize((W, H), Image.LANCZOS)
    .point(lambda v: 255 if v > 20 else 0).save(os.path.join(THEME, "mask.png"), optimize=True))
shutil.copy(os.path.join(REN, "scene.json"), os.path.join(THEME, "scene.json"))

# ---- the page
def uri(path, as_jpeg=False):
    if as_jpeg:
        b = io.BytesIO(); Image.open(path).convert("RGB").save(b, "JPEG", quality=94); return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    mime = "image/png" if path.endswith(".png") else "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(open(path, "rb").read()).decode())
t = open(os.path.join(HERE, "template.html")).read()
for key, path, jpg in (("__PHOTO__", os.path.join(ASSETS, "panel_photo.jpg"), False), ("__WINA__", os.path.join(MOCK, "winA.png"), False), ("__LITA__", os.path.join(MOCK, "litA.png"), False), ("__CELLSA__", os.path.join(MOCK, "cellsA.png"), False),
                       ("__BDAY__", os.path.join(THEME, "day.png"), True), ("__BDUSK__", os.path.join(THEME, "dusk.png"), True),
                       ("__BNIGHT__", os.path.join(THEME, "night_dark.png"), True), ("__BLIT__", os.path.join(THEME, "night_lit.png"), True),
                       ("__BMASK__", os.path.join(THEME, "mask.png"), False)):
    t = t.replace(key, uri(path, jpg))
open(os.path.join(MOCK, "cruise-mockups.html"), "w").write(t)

# ---- a preview sheet: day, dusk, night (all lit) and a close-up
def load(p): return Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
tiles = [("Day", load(os.path.join(THEME, "day.png"))), ("Dusk", load(os.path.join(THEME, "dusk.png"))),
         ("Night (all windows lit)", load(os.path.join(THEME, "night_lit.png")))]
close = os.path.join(REN, "closeup_boats.png")
if os.path.exists(close): tiles.append(("Lifeboats close-up, day", load(close)))
pad, lab = 16, 30
sheet = Image.new("RGB", (2*W + 3*pad, 2*(H + lab) + 3*pad), (18, 20, 24)); d = ImageDraw.Draw(sheet)
try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
except OSError: f = ImageFont.load_default()
for i, (name, im) in enumerate(tiles):
    x = pad + (i % 2)*(W + pad); y = pad + (i // 2)*(H + lab + pad)
    d.text((x, y), name, fill=(220, 220, 220), font=f); sheet.paste(im, (x, y + lab))
sheet.save(os.path.join(MOCK, "preview.png"))
bow = os.path.join(REN, "closeup_bow.png")
if os.path.exists(bow): Image.open(bow).convert("RGB").crop((900, 420, 1600, 860)).save(os.path.join(MOCK, "bow-detail.png"))
print("plates ->", THEME); print("page   ->", os.path.join(MOCK, "cruise-mockups.html"))
