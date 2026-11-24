"""The countdown apps: each a whole trip (the cruise, the castle), an app of its own in /apps/<id>
(see docs/apps.md), built on this runtime. The runtime is apps/countdown; an app starts it with its
`run` (`exec /apps/countdown/launch`), in the app's own folder.

A countdown app is a folder with an app.json:
    {"id": "castle", "name": "Magic Kingdom", "version": "1.0.0", "runtime": "countdown", "api": 2,
     "scene": {"engine": "scene", "dir": "scenes", "default": "magic-kingdom"},
     "screens": [{"id": "waits", "file": "board.py", "class": "WaitsScreen", "enabled": "WAITS", "secs": "WAITS_SECS"}],
     "settings": [...], "countdown": {...}, "short_names": {...}, "exclude": [...]}
and its own `run`, and optionally a `service` (its background job: S99app runs it beside the app) and
a defaults.conf (its own settings' first values).

- the scene: what's behind the countdown, a folder in scene.dir (THEME in its settings picks one;
  scene.default otherwise). engine "scene": the drawing library's (vfx_*); its theme.json says which
  of its effects the scene has ("effects"; all of them, the ship's, if it doesn't say).
- screens: shown in turn with the countdown, each for its "secs" setting (seconds) while its
  "enabled" setting isn't 0. A screen is a class taking the App, with run(seconds) (see the cruise's map.py).
- data and settings: its own folder, APP_DATA (/apps/data/<id>): countdown.conf, and whatever it fetches.
"""
import importlib.util, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = os.environ.get("SYSTEM_DIR") or os.path.join(os.path.dirname(HERE), "system")   # (the system package: /apps/system)
if SYSTEM not in sys.path: sys.path.insert(0, SYSTEM)
from sysapps import DEVICE_CONF, DEVICE_KEYS, read_conf, device_path, read_settings, manifest_path, installed   # noqa: E402

API = 2                                  # the app.json "api" this runtime understands (also in the API file)
CONF = "countdown.conf"                  # each app's settings, in its APP_DATA
OLD_DATA = "/apps/data/vacation"         # where every trip's settings and data were before apps
APP_KEYS = ("MODULE",)                   # settings that meant something only before apps


def ensure_device(app, conf_path):
    """Make device.conf the first time: the touch calibration and CPU clock from this app's settings,
    the brightness from the chess clock's (it had the only brightness settings)."""
    path = device_path(app.data_dir)
    if os.path.exists(path): return path
    mine, chess = read_conf(conf_path), read_conf(os.path.join(os.path.dirname(path), "chess", "fbclock.conf"))
    lines = ["# The device's own settings, shared by every app (Settings > Display in a countdown app;",
             "# the chess clock's brightness sliders). KEY=VALUE lines."]
    for k in DEVICE_KEYS:
        v = mine.get(k) if k.startswith("TOUCH_") or k == "CPU_MHZ" else chess.get(k)
        if v not in (None, ""): lines.append("%s=%s" % (k, v))
    with open(path + ".tmp", "w") as f: f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    print("countdown: device settings started in %s" % path, flush=True)
    return path


class App:
    """A countdown app: its manifest, scene and screens (vacation.py's `app.module`)."""

    def __init__(self, path, data_dir):
        self.dir = os.path.abspath(path)
        mp = manifest_path(self.dir)
        if not mp: sys.exit("countdown: %s has no app.json" % self.dir)
        self.meta = json.load(open(mp))
        self.id = self.meta["id"]
        self.name = self.meta.get("name", self.id)
        if self.meta.get("api", API) > API:
            print("countdown: %s wants a newer runtime (api %s; this is %d)" % (self.id, self.meta["api"], API), flush=True)
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def scene_dir(self, conf):
        """The scene's folder: THEME from the settings if the app has it, else its default."""
        sc = self.meta.get("scene", {})
        base = os.path.join(self.dir, sc.get("dir", "scenes"))
        name = conf.get("THEME") or sc.get("default", "")
        if not os.path.isdir(os.path.join(base, name)): name = sc.get("default", name)
        return os.path.join(base, name)

    def screens(self):
        """[(spec from app.json, the screen's class)], in order; a screen that won't load is left out."""
        if self.dir not in sys.path: sys.path.insert(0, self.dir)          # (so a screen can import its own files)
        out = []
        for spec in self.meta.get("screens", []):
            path = os.path.join(self.dir, spec["file"])
            try:
                loader = importlib.util.spec_from_file_location("%s_%s" % (self.id, spec["id"]), path)
                mod = importlib.util.module_from_spec(loader); loader.loader.exec_module(mod)
                out.append((spec, getattr(mod, spec["class"])))
            except Exception as e:                                        # (one broken screen shouldn't stop the countdown)
                print("countdown: %s's screen %s didn't load: %s" % (self.id, spec.get("id"), e), flush=True)
        return out


def _conf_lines(path):
    try: return open(path).read().splitlines()
    except OSError: return []


def _keys(lines):
    return {l.split("=", 1)[0].strip() for l in lines if "=" in l and not l.lstrip().startswith("#")}


def settings_file(app, old_data=OLD_DATA):
    """The app's countdown.conf, made the first time: from the settings it had before apps (the shared
    vacation.conf: touch calibration, fireworks, the date), else another countdown app's (so the
    calibration carries over), else the runtime's defaults; then any of the app's own defaults.conf
    keys it lacks. The app's data from before apps (/apps/data/vacation/<id>/) moves in too."""
    path = os.path.join(app.data_dir, CONF)
    if os.path.exists(path): return path
    old_mine = os.path.join(old_data, app.id)
    if os.path.isdir(old_mine):
        for f in os.listdir(old_mine):
            src, dst = os.path.join(old_mine, f), os.path.join(app.data_dir, f)
            if not os.path.exists(dst): shutil.move(src, dst)
        print("countdown: moved %s's data from %s" % (app.id, old_mine), flush=True)
    sibling = [os.path.join(os.path.dirname(app.data_dir), d, CONF) for d in sorted(os.listdir(os.path.dirname(app.data_dir)))]
    start = next((p for p in [os.path.join(old_data, "vacation.conf")] + sibling if os.path.isfile(p) and p != path),
                 os.path.join(HERE, CONF))
    lines = [l for l in _conf_lines(start) if l.split("=", 1)[0].strip() not in APP_KEYS]
    if start != os.path.join(HERE, CONF):
        lines = [("THEME=" if l.startswith("THEME=") else l) for l in lines]   # (another app's scene isn't this one's)
    have = _keys(lines)
    extra = [l for l in _conf_lines(os.path.join(app.dir, "defaults.conf")) if "=" not in l or l.split("=", 1)[0].strip() not in have]
    if extra: lines += ["", "# %s's own" % app.name] + extra
    with open(path + ".tmp", "w") as f: f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    print("countdown: settings for %s started from %s" % (app.id, start), flush=True)
    return path


