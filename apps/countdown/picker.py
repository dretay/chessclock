"""The app picker: every installed app (a picture and its name), and a tap starts it. Settings > Apps
opens it in every app (the countdown's page 1, the chess clock's Settings), through `pick`, which
stops the app first and starts the one picked after: this prints the picked app's id, or nothing
(‹ Back, or a minute untouched) to start the one that was running again.

It draws with the countdown runtime's library, over the blurred scene of the app that was running (or
the first countdown app's), and reads the touch screen with that app's calibration. An app's picture
is its icon.rgb.gz (ICON_W x ICON_H raw RGB, tools/themegen/app_icon.py), else just its name.
On a desktop: PICKER_APPS (default /apps), PICKER_CURRENT, PICKER_TIMEOUT (seconds), and the
VACATION_LIB, VACATION_FB and VACATION_TOUCH_SCRIPT of vacation.py.
"""
import ctypes, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apps
import vacation_layout as L
import vacation_touch as touch
from vacation_text import Text

ROOT = os.environ.get("PICKER_APPS", "/apps")
DATA = os.path.join(ROOT, "data")
ICON_W, ICON_H = 240, 144
COLS, GAP, TOP, ROW_H = 3, 20, 92, 196
BACK = (646, 18, 776, 64)
TIMEOUT = float(os.environ.get("PICKER_TIMEOUT", "60"))


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


def current():
    if os.environ.get("PICKER_CURRENT"): return os.environ["PICKER_CURRENT"]
    try: return open(os.path.join(ROOT, "current")).read().strip()
    except OSError: return ""


def scene_of(app_dir):
    """A countdown app's default scene folder, or None."""
    mp = apps.manifest_path(app_dir)
    try: meta = json.load(open(mp)) if mp else {}
    except (OSError, ValueError): return None
    sc = meta.get("scene")
    if not sc: return None
    d = os.path.join(app_dir, sc.get("dir", "scenes"), sc.get("default", ""))
    return d if os.path.isfile(os.path.join(d, "theme.json")) else None


def read_conf(path):
    conf = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    return conf


def conf_of(app_id):
    """The touch calibration: the running app's settings, else any app's that has it."""
    tried = [os.path.join(DATA, app_id, f) for f in ("countdown.conf", "fbclock.conf")]
    tried += sorted(os.path.join(DATA, d, "countdown.conf") for d in (os.listdir(DATA) if os.path.isdir(DATA) else []))
    for p in tried + [os.path.join(HERE, "countdown.conf")]:
        if os.path.isfile(p):
            c = read_conf(p)
            if "TOUCH_X_MIN" in c: return c
    return {}


def boxes(n):
    """Each app's card (its picture's box), up to two rows of three."""
    x0 = (L.W - COLS * ICON_W - (COLS - 1) * GAP) // 2
    top = TOP if n > COLS else (L.H - ICON_H) // 2 - 10                # (one row: in the middle)
    return [(x0 + (i % COLS) * (ICON_W + GAP), top + (i // COLS) * ROW_H) for i in range(min(n, 2 * COLS))]


def main():
    found = apps.installed(ROOT)
    cur = current()
    by_id = {a[0]: a for a in found}
    scene = scene_of(by_id[cur][2]) if cur in by_id else None
    scene = scene or next((s for s in (scene_of(a[2]) for a in found) if s), None)
    if not scene: sys.exit("picker: no countdown app to draw with")
    fx = ctypes.CDLL(os.environ.get("VACATION_LIB", os.path.join(HERE, "fx", "libvacfx.so")))
    if fx.vfx_open(os.environ.get("VACATION_FB", "/dev/fb0").encode(), scene.encode()) != 0: sys.exit("picker: no display")
    ui_dir = os.environ.get("VACATION_UI_DIR", os.path.join(HERE, "ui"))
    if fx.vfx_ui_open(ui_dir.encode(), scene.encode()) != 0: sys.exit("picker: no Settings images")
    t = Text(fx)
    cards = boxes(len(found))
    for (aid, name, d), (x, y) in zip(found, cards):        # (pictures first: they go into the background)
        if os.path.isfile(os.path.join(d, "icon.rgb.gz")): fx.vfx_ui_bg_tile(d.encode(), b"icon.rgb.gz", x, y, ICON_W, ICON_H)
    fx.vfx_ui_bg(0, 0, L.W, L.H, 256)
    t.draw("title", "Apps", 36, 58, L.IVORY)
    fx.vfx_ui_round(*BACK, 14, rgb((255, 255, 255)), 22, rgb((255, 255, 255)), 120)
    t.draw("button", "‹ Back", (BACK[0] + BACK[2]) // 2, BACK[1] + 34, L.IVORY, "m")
    for (aid, name, d), (x, y) in zip(found, cards):
        here = aid == cur
        if not os.path.isfile(os.path.join(d, "icon.rgb.gz")):
            fx.vfx_ui_round(x, y, x + ICON_W, y + ICON_H, 14, rgb(L.PANEL_FILL), L.PANEL_ALPHA, rgb((255, 255, 255)), L.PANEL_LINE_ALPHA)
        fx.vfx_ui_round(x - 3, y - 3, x + ICON_W + 3, y + ICON_H + 3, 16, 0, 0,
                        rgb(L.GOLD if here else (255, 255, 255)), 255 if here else 70)
        t.draw("label", t.fit("label", name, ICON_W), x + ICON_W // 2, y + ICON_H + 34, L.GOLD if here else L.IVORY, "m")
    fx.vfx_ui_flush()

    tp = touch.Touch.open(conf_of(cur))
    picked, start = None, time.monotonic()
    while time.monotonic() - start < TIMEOUT and picked is None:
        for ev, x, y in (tp.poll(time.monotonic() - start) if tp else []):
            if ev != "up": continue
            if BACK[0] - 10 <= x < BACK[2] + 10 and y < BACK[3] + 16: picked = ""; break
            for (aid, _, _), (bx, by) in zip(found, cards):
                if bx - GAP // 2 <= x < bx + ICON_W + GAP // 2 and by - 12 <= y < by + ROW_H - 12: picked = aid; break
            if picked is not None: break
        if tp is None: break
        time.sleep(0.02)
    # what starts next takes a few seconds: say so, and leave it on the screen until that app draws
    name = (by_id.get(picked) or by_id.get(cur) or ("", ""))[1]
    if name:
        box = (L.W // 2 - 230, L.H // 2 - 50, L.W // 2 + 230, L.H // 2 + 50)
        fx.vfx_ui_round(*box, 18, rgb((8, 14, 30)), 240, rgb(L.GOLD), 160)
        msg = t.fit("label", "Starting %s" % name, box[2] - box[0] - 80)
        left = L.W // 2 - (t.width("label", msg) + 10 + 30) // 2; base = box[1] + 58
        t.draw("label", msg, left, base, L.IVORY)
        fx.vfx_ui_flush()
        anim = os.path.join(HERE, "splashanim")                  # (pulsing dots after it, until the app draws)
        if os.access(anim, os.X_OK):
            import subprocess
            subprocess.Popen([anim, str(left + t.width("label", msg) + 14), str(base - 5)], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fx.vfx_ui_close(); fx.vfx_close()
    if picked: print(picked)


if __name__ == "__main__":
    main()
