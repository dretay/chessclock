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
import sysapps as apps
import vacation_layout as L
import vacation_touch as touch
from vacation_text import Text

ROOT = os.environ.get("PICKER_APPS", "/apps")
DATA = os.environ.get("PICKER_DATA") or os.path.join(ROOT, "data")     # (the previewer's own, on a desktop)
ICON_W, ICON_H = 240, 144
COLS, GAP, TOP, ROW_H = 3, 20, 92, 196
BACK = (646, 18, 776, 64)
GET = (466, 18, 630, 64)                  # Get apps › (the catalog), when there's WiFi
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
    """The touch calibration: the device's (device.conf), else the running app's, else any app's that has it."""
    tried = [os.path.join(DATA, "device.conf")] + [os.path.join(DATA, app_id, f) for f in ("countdown.conf", "fbclock.conf")]
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


def network():
    """Get apps needs the network: a kernel with WiFi (PICKER_NETWORK: try it on a desktop)."""
    return os.path.isdir("/sys/class/ieee80211") or bool(os.environ.get("PICKER_NETWORK"))


def installed_apps():
    found = apps.installed(ROOT)
    if os.path.exists(os.path.join(DATA, "locked")):                # (locked to signed apps: only those)
        import shutil, subprocess
        if shutil.which("modinstall"):                                  # (the board's; a desktop preview has none)
            found = [a for a in found if subprocess.run(["modinstall", "--verify-installed", a[2]], stdout=subprocess.DEVNULL,
                                                        stderr=subprocess.DEVNULL).returncode == 0]
    return found


def button(fx, t, box, label, gold=False):
    if gold: fx.vfx_ui_round(*box, 14, rgb(L.GOLD), 255, 0, 0)
    else: fx.vfx_ui_round(*box, 14, rgb((255, 255, 255)), 22, rgb((255, 255, 255)), 120)
    t.draw("button" if label.startswith("‹") else "small", label, (box[0] + box[2]) // 2,
           box[1] + (34 if label.startswith("‹") else 29), L.DARK if gold else L.IVORY, "m")


def draw_grid(fx, t, scene, ui_dir, found, cur):
    """The apps: each one's picture and name (the running one in gold). Returns their cards' places."""
    fx.vfx_ui_close()
    if fx.vfx_ui_open(ui_dir.encode(), scene.encode()) != 0: sys.exit("picker: no Settings images")
    cards = boxes(len(found))
    for (aid, name, d), (x, y) in zip(found, cards):        # (pictures first: they go into the background)
        if os.path.isfile(os.path.join(d, "icon.rgb.gz")): fx.vfx_ui_bg_tile(d.encode(), b"icon.rgb.gz", x, y, ICON_W, ICON_H)
    fx.vfx_ui_bg(0, 0, L.W, L.H, 256)
    t.draw("title", "Apps", 36, 58, L.IVORY)
    button(fx, t, BACK, "‹ Back")
    if network(): button(fx, t, GET, "Get apps ›")
    for (aid, name, d), (x, y) in zip(found, cards):
        here = aid == cur
        if not os.path.isfile(os.path.join(d, "icon.rgb.gz")):
            fx.vfx_ui_round(x, y, x + ICON_W, y + ICON_H, 14, rgb(L.PANEL_FILL), L.PANEL_ALPHA, rgb((255, 255, 255)), L.PANEL_LINE_ALPHA)
        fx.vfx_ui_round(x - 3, y - 3, x + ICON_W + 3, y + ICON_H + 3, 16, 0, 0,
                        rgb(L.GOLD if here else (255, 255, 255)), 255 if here else 70)
        t.draw("label", t.fit("label", name, ICON_W), x + ICON_W // 2, y + ICON_H + 34, L.GOLD if here else L.IVORY, "m")
    fx.vfx_ui_flush()
    return cards


def taps(tp, start, timeout):
    """Each tap's (x, y) until timeout seconds without one (then None)."""
    last = time.monotonic()
    while time.monotonic() - last < timeout:
        for ev, x, y in (tp.poll(time.monotonic() - start) if tp else []):
            if ev == "up": last = time.monotonic(); yield x, y
        if tp is None: break
        time.sleep(0.02)
    yield None


def note(fx, t, text, sub=None):
    """A message in the middle of the screen."""
    box = (L.W // 2 - 260, L.H // 2 - 50, L.W // 2 + 260, L.H // 2 + 50)
    fx.vfx_ui_round(*box, 18, rgb((8, 14, 30)), 240, rgb(L.GOLD), 160)
    t.draw("label", t.fit("label", text, box[2] - box[0] - 40), L.W // 2, box[1] + (48 if sub else 58), L.IVORY, "m")
    if sub: t.draw("small", t.fit("small", sub, box[2] - box[0] - 40), L.W // 2, box[1] + 78, L.DIM, "m")
    fx.vfx_ui_flush()


def get_apps(fx, t, tp, start, scene, ui_dir):
    """Get apps: the catalog's apps, each with Install / Update / Installed; a tap installs it."""
    import catalog
    work = os.path.join(DATA, "packages")
    url = (read_conf(os.path.join(DATA, "device.conf")).get("CATALOG_URL") or catalog.DEFAULT_URL)

    def page(msg=None, sub=None):
        fx.vfx_ui_close()
        fx.vfx_ui_open(ui_dir.encode(), scene.encode())
        fx.vfx_ui_bg(0, 0, L.W, L.H, 256)
        t.draw("title", "Get apps", 36, 58, L.IVORY)
        button(fx, t, BACK, "‹ Back")
        if msg: note(fx, t, msg, sub)
        fx.vfx_ui_flush()

    page("Checking the catalog", "one moment")
    try: cat = catalog.load(url, work)
    except catalog.CatalogError as e:
        page("Couldn't get the catalog", str(e))
        for tap in taps(tp, start, 30): break
        return
    entries = [a for a in cat.get("apps", []) if a.get("kind") != "runtime"]
    rows = []

    def draw_list():
        page()
        fx.vfx_ui_round(20, 78, L.W - 20, 392, 16, rgb(L.PANEL_FILL), L.PANEL_ALPHA, rgb((255, 255, 255)), L.PANEL_LINE_ALPHA)
        rows.clear()
        for i, e in enumerate(entries[:5]):
            y = 92 + i * 60
            st = catalog.status(e, ROOT)
            t.draw("label", t.fit("label", e.get("name", e["id"]), 440), 44, y + 34, L.IVORY)
            t.draw("small", "version %s" % e.get("version", "?"), 520, y + 33, L.DIM, "r")
            box = (600, y + 6, 760, y + 50)
            if st == "Installed": t.draw("small", "Installed", (box[0] + box[2]) // 2, box[1] + 29, L.DIM, "m")
            else: button(fx, t, box, st, gold=True)
            rows.append((y, e, st))
        if not entries: note(fx, t, "No apps in the catalog yet")
        fx.vfx_ui_flush()

    draw_list()
    for tap in taps(tp, start, TIMEOUT):
        if tap is None: return
        x, y = tap
        if BACK[0] - 10 <= x < BACK[2] + 10 and y < BACK[3] + 16: return
        for ry, e, st in rows:
            if ry <= y < ry + 60 and st != "Installed":
                shown = {"say": "Downloading %s" % e["name"]}
                def say(text): shown["say"] = text; note(fx, t, text, "one moment")
                def progress(f): note(fx, t, shown["say"], "%d%%" % round(f * 100))
                try: done = catalog.install(e, cat, ROOT, work, progress, say); note(fx, t, "Installed %s" % e["name"], done)
                except catalog.CatalogError as err: note(fx, t, "Couldn't install %s" % e["name"], str(err))
                time.sleep(2.5); draw_list()
                break


def choose(fx, t, tp, scene, ui_dir, cur):
    """The grid until an app is picked: its id, or "" (‹ Back, or a minute untouched)."""
    start = time.monotonic()
    while True:
        found = installed_apps()
        cards = draw_grid(fx, t, scene, ui_dir, found, cur)
        again = False
        for tap in taps(tp, start, TIMEOUT):
            if tap is None: return ""
            x, y = tap
            if BACK[0] - 10 <= x < BACK[2] + 10 and y < BACK[3] + 16: return ""
            if network() and GET[0] - 10 <= x < GET[2] + 10 and y < GET[3] + 16:
                get_apps(fx, t, tp, start, scene, ui_dir); again = True; break   # (then the grid again: there may be more)
            hit = next((aid for (aid, _, _), (bx, by) in zip(found, cards)
                        if bx - GAP // 2 <= x < bx + ICON_W + GAP // 2 and by - 12 <= y < by + ROW_H - 12), None)
            if hit: return hit
        if not again: return ""


def starting(fx, t, name):
    """"Starting <app>", with the pulsing dots after it, left on the screen until that app draws (it takes
    a few seconds to start)."""
    box = (L.W // 2 - 230, L.H // 2 - 50, L.W // 2 + 230, L.H // 2 + 50)
    fx.vfx_ui_round(*box, 18, rgb((8, 14, 30)), 240, rgb(L.GOLD), 160)
    msg = t.fit("label", "Starting %s" % name, box[2] - box[0] - 80)
    left = L.W // 2 - (t.width("label", msg) + 10 + 30) // 2; base = box[1] + 58
    t.draw("label", msg, left, base, L.IVORY)
    fx.vfx_ui_flush()
    anim = os.path.join(HERE, "splashanim")
    if os.access(anim, os.X_OK):
        import subprocess
        subprocess.Popen([anim, str(left + t.width("label", msg) + 14), str(base - 5)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def choose_here(app):
    """Settings > Apps in a countdown app: the picker in the app's own process (no second Python to start:
    it opens at once). Picking another app has the launcher switch (`app NAME`: it stops this one; APP_SWITCH
    in the previewer); this one, or ‹ Back, carries on."""
    fx, t, cur = app.fx, Text(app.fx), current()
    picked = choose(fx, t, app.touch, app.theme_dir, app.ui_dir, cur)
    if picked and picked != cur:
        name = dict((a[0], a[1]) for a in installed_apps()).get(picked, picked)
        starting(fx, t, name)
        import subprocess
        try:
            subprocess.Popen([os.environ.get("APP_SWITCH", "app"), picked], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            until = time.monotonic() + 30
            while app.running and time.monotonic() < until: app.tick()          # (until the launcher stops this app)
        except OSError as e:
            print("picker: couldn't switch to %s: %s" % (picked, e), flush=True)
    fx.vfx_ui_close()


def main():
    cur = current()
    found = installed_apps()
    by_id = {a[0]: a for a in found}
    scene = scene_of(by_id[cur][2]) if cur in by_id else None
    scene = scene or next((s for s in (scene_of(a[2]) for a in found) if s), None)
    if not scene: sys.exit("picker: no countdown app to draw with")
    fx = ctypes.CDLL(os.environ.get("VACATION_LIB", os.path.join(HERE, "fx", "libvacfx.so")))
    if fx.vfx_open(os.environ.get("VACATION_FB", "/dev/fb0").encode(), scene.encode()) != 0: sys.exit("picker: no display")
    ui_dir = os.environ.get("VACATION_UI_DIR", os.path.join(HERE, "ui"))
    t = Text(fx)
    tp = touch.Touch.open(conf_of(cur))
    picked = choose(fx, t, tp, scene, ui_dir, cur)
    by_id = {a[0]: a for a in installed_apps()}
    name = (by_id.get(picked) or by_id.get(cur) or ("", ""))[1]
    if name: starting(fx, t, name)
    fx.vfx_ui_close(); fx.vfx_close()
    if picked: print(picked)


if __name__ == "__main__":
    main()
