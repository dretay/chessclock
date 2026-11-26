"""The app picker: every installed app (a picture and its name), and a tap starts it. Settings > Apps
opens it in every app (the countdown's page 1), through `pick`, which
stops the app first and starts the one picked after: this prints the picked app's id, or nothing
(‹ Back, or a minute untouched) to start the one that was running again.

It draws with the countdown runtime's library, over the blurred scene of the app that was running (or
the first countdown app's), and reads the touch screen with that app's calibration. An app's picture
is its icon.rgb.gz (ICON_W x ICON_H raw RGB, tools/themegen/app_icon.py), else just its name.
On a desktop: PICKER_APPS (default /apps), PICKER_CURRENT, PICKER_TIMEOUT (seconds), and the
VACATION_LIB, VACATION_FB and VACATION_TOUCH_SCRIPT of vacation.py.
"""
import ctypes, json, os, subprocess, sys, time

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
MORE = (300, 18, 450, 64)                 # More ›: the next page of apps, when there are more than a page
PER_PAGE = 2 * COLS
LIST_ROWS = 5                             # Get apps: rows a page
MORE_LIST = (600, 404, 760, 452)
ALL = (330, 18, 630, 64)                  # Update all (N): every app (and runtime) with an update
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
    if not os.path.isfile(path): return conf                         # (a new card: no device.conf yet)
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    return conf


def conf_of(app_id):
    """The touch calibration: the device's (device.conf), else the running app's, else any app's that has it."""
    tried = [os.path.join(DATA, "device.conf")] + [os.path.join(DATA, app_id, "countdown.conf")]
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


def pages(n, per):
    return max(1, (n + per - 1) // per)


def draw_grid(fx, t, scene, ui_dir, found, cur):
    """The apps (a page of them: found is that page's): each one's picture and name (the running one in
    gold). Returns their cards' places."""
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
    """Each tap's (x, y) until timeout seconds without one (then None). The time spent on a tap (a
    download, an install: minutes) doesn't count: the clock starts again when the page is back."""
    last = time.monotonic()
    while time.monotonic() - last < timeout:
        for ev, x, y in (tp.poll(time.monotonic() - start) if tp else []):
            if ev == "up":
                yield x, y
                last = time.monotonic()
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


RESTART_NOW = (L.W // 2 - 250, L.H // 2 + 20, L.W // 2 - 10, L.H // 2 + 70)
LATER = (L.W // 2 + 10, L.H // 2 + 20, L.W // 2 + 250, L.H // 2 + 70)


def ask_restart(fx, t, tp, start, version):
    """A base system just installed: restart into it now (True), or later (False: Get apps shows Restart)."""
    box = (L.W // 2 - 280, L.H // 2 - 90, L.W // 2 + 280, L.H // 2 + 90)
    fx.vfx_ui_round(*box, 18, rgb((8, 14, 30)), 245, rgb(L.GOLD), 160)
    t.draw("label", "Base %s is installed" % version, L.W // 2, box[1] + 50, L.IVORY, "m")
    t.draw("small", "it's used from the next start", L.W // 2, box[1] + 80, L.DIM, "m")
    button(fx, t, RESTART_NOW, "Restart now", gold=True)
    button(fx, t, LATER, "Later")
    fx.vfx_ui_flush()
    for tap in taps(tp, start, TIMEOUT):
        if tap is None: return False
        x, y = tap
        if RESTART_NOW[1] - 12 <= y < RESTART_NOW[3] + 12:
            if RESTART_NOW[0] - 12 <= x < RESTART_NOW[2] + 12: return True
            if LATER[0] - 12 <= x < LATER[2] + 12: return False
    return False


def restart():
    """Into the slot just installed: the board goes down at once (the app is stopped with it)."""
    os.sync(); subprocess.run(["reboot"]); time.sleep(60)


def get_apps(fx, t, tp, start, scene, ui_dir):
    """Get apps: the catalog's apps, each with Install / Update / Installed; a tap installs it. First, when
    the catalog has one and the card has two root slots: the base system (Update / Installed, then
    Restart once an update is installed: it's used from the next start)."""
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
    # (the apps; a runtime only when it's installed and the catalog has a newer one: the system package
    # itself, say, with this page in it)
    entries = [a for a in cat.get("apps", []) if a.get("kind") != "runtime" or catalog.status(a, ROOT) == "Update"]
    entries.sort(key=lambda a: a.get("kind") != "runtime")             # (runtime updates first: on page 1)
    base = catalog.base_entry(cat)
    state = catalog.slots() if base else {}
    if base and catalog.base_status(base, state): entries.insert(0, dict(base, id="base", name="Base system", is_base=True))
    if state.get("failed"):                              # (an update that didn't start: said once, then forgotten)
        page("The last system update didn't start", "the frame went back to base %s" % (catalog.running_base() or "the one before"))
        for tap in taps(tp, start, 6): break
        catalog.clear_failed()
    rows = []
    at = {"page": 0}

    def draw_list():
        page()
        fx.vfx_ui_round(20, 78, L.W - 20, 392, 16, rgb(L.PANEL_FILL), L.PANEL_ALPHA, rgb((255, 255, 255)), L.PANEL_LINE_ALPHA)
        rows.clear()
        n = pages(len(entries), LIST_ROWS)
        at["page"] %= n
        first = at["page"] * LIST_ROWS
        for i, e in enumerate(entries[first:first + LIST_ROWS]):
            y = 92 + i * 60
            st = catalog.base_status(e) if e.get("is_base") else catalog.status(e, ROOT)
            t.draw("label", t.fit("label", e.get("name", e["id"]), 440), 44, y + 34, L.IVORY)
            shown_version = catalog.running_base() if e.get("is_base") and st == "Installed" else e.get("version", "?")
            t.draw("small", "version %s" % shown_version, 520, y + 33, L.DIM, "r")
            box = (600, y + 6, 760, y + 50)
            if st == "Installed": t.draw("small", "Installed", (box[0] + box[2]) // 2, box[1] + 29, L.DIM, "m")
            else: button(fx, t, box, st, gold=True)
            rows.append((y, e, st))
        if not entries: note(fx, t, "No apps in the catalog yet")
        if n > 1: button(fx, t, MORE_LIST, "More  %d/%d" % (at["page"] + 1, n))
        if len(updatable()) > 1: button(fx, t, ALL, "Update all (%d)" % len(updatable()), gold=True)
        fx.vfx_ui_flush()

    def restart_now(version):
        """After a base install: the question, and the restart if it's now (True)."""
        draw_list()                                      # (a clean page behind the question)
        if ask_restart(fx, t, tp, start, version):
            note(fx, t, "Restarting", "back in about a minute"); restart(); return True
        return False

    def updatable():
        """The apps and runtimes with an update (runtimes first), not the base system: it needs a restart."""
        return [e for e in entries if not e.get("is_base") and catalog.status(e, ROOT) == "Update"]

    def update_all():
        todo, failed = updatable(), []
        for i, e in enumerate(todo, 1):
            if catalog.status(e, ROOT) != "Update": continue                 # (a runtime an app before it brought)
            shown = {"say": "Updating %d of %d: %s" % (i, len(todo), e["name"])}
            def say(text, i=i, e=e): shown["say"] = "Updating %d of %d: %s" % (i, len(todo), e["name"]); note(fx, t, shown["say"], "one moment")
            def progress(f): note(fx, t, shown["say"], "%d%%" % round(f * 100))
            try: catalog.install(e, cat, ROOT, work, progress, say)
            except catalog.CatalogError as err: failed.append(e["name"]); print("picker: %s: %s" % (e["name"], err), flush=True)
        if failed: note(fx, t, "Updated %d of %d" % (len(todo) - len(failed), len(todo)), "couldn't update " + ", ".join(failed))
        else: note(fx, t, "Updated %d apps" % len(todo), "all up to date")
        time.sleep(2.5)

    draw_list()
    for tap in taps(tp, start, TIMEOUT):
        if tap is None: return
        x, y = tap
        if BACK[0] - 10 <= x < BACK[2] + 10 and y < BACK[3] + 16: return
        if len(entries) > LIST_ROWS and MORE_LIST[0] - 10 <= x < MORE_LIST[2] + 10 and y >= MORE_LIST[1] - 10:
            at["page"] += 1; draw_list(); continue
        if len(updatable()) > 1 and ALL[0] - 10 <= x < ALL[2] + 10 and y < ALL[3] + 16:
            update_all(); draw_list(); continue
        for ry, e, st in rows:
            if ry <= y < ry + 60 and st != "Installed":
                if st == "Restart":                          # (the base system: into the slot just installed)
                    note(fx, t, "Restarting", "back in about a minute"); restart(); return
                shown = {"say": "Downloading %s" % e["name"]}
                def say(text): shown["say"] = text; note(fx, t, text, "a few minutes" if e.get("is_base") else "one moment")
                def progress(f): note(fx, t, shown["say"], "%d%%" % round(f * 100))
                try:
                    if e.get("is_base"):
                        catalog.install_base(e, work, progress, say)
                        if restart_now(e["version"]): return
                    else:
                        done = catalog.install(e, cat, ROOT, work, progress, say); note(fx, t, "Installed %s" % e["name"], done)
                except catalog.CatalogError as err: note(fx, t, "Couldn't install %s" % e["name"], str(err))
                time.sleep(2.5); draw_list()
                break


def choose(fx, t, tp, scene, ui_dir, cur):
    """The grid until an app is picked: its id, or "" (‹ Back, or a minute untouched)."""
    start = time.monotonic()
    page = 0
    while True:
        everything = installed_apps()
        n = pages(len(everything), PER_PAGE)
        page %= n
        found = everything[page * PER_PAGE:(page + 1) * PER_PAGE]
        cards = draw_grid(fx, t, scene, ui_dir, found, cur)
        if n > 1: button(fx, t, MORE, "More  %d/%d" % (page + 1, n)); fx.vfx_ui_flush()
        again = False
        for tap in taps(tp, start, TIMEOUT):
            if tap is None: return ""
            x, y = tap
            if BACK[0] - 10 <= x < BACK[2] + 10 and y < BACK[3] + 16: return ""
            if network() and GET[0] - 10 <= x < GET[2] + 10 and y < GET[3] + 16:
                note(fx, t, "Checking the catalog", "one moment")          # (at once: loading the network code takes seconds)
                get_apps(fx, t, tp, start, scene, ui_dir); again = True; break   # (then the grid again: there may be more)
            if n > 1 and MORE[0] - 10 <= x < MORE[2] + 10 and y < MORE[3] + 16:
                page += 1; again = True; break
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
