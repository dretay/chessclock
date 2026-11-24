"""The countdown's modules: each a whole trip, in its own folder under modules/ (see README.md, "Modules").

A module is a folder with a module.json:
    {"id": "cruise", "name": "Disney cruise", "version": "1.0.0", "api": 1,
     "scene": {"engine": "scene", "dir": "scenes", "default": "dream"},
     "screens": [{"id": "map", "file": "map.py", "class": "MapScreen", "enabled": "MAP", "secs": "MAP_SECS"}]}
and, by convention, an executable `service` (its background job, run by the app's own service).

- the scene: what's behind the countdown, a folder in scene.dir (vacation.conf's THEME picks one;
  scene.default otherwise). engine "scene": the drawing library's (vfx_*); its theme.json says which
  of its effects the scene has ("effects"; all of them, the ship's, if it doesn't say).
- screens: shown in turn with the countdown, each for its "secs" setting (seconds) while its
  "enabled" setting isn't 0. A screen is a class taking the App, with run(seconds) (see map.py).
- data: the module keeps whatever it fetches or saves in its own folder, $APP_DATA/<id>
  (MODULE_DATA for its service; Module.data_dir for its screens).

vacation.conf's MODULE picks the module (cruise by default).
"""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("VACATION_MODULES", os.path.join(HERE, "modules"))
DEFAULT = "cruise"
API = 1                                  # the module.json "api" this host understands

# files that lived in APP_DATA itself before modules: moved into their module's folder on first start
MIGRATE = {"cruise": ["ships.csv", "ais.key"]}


class Module:
    def __init__(self, path, app_data):
        self.dir = path
        self.meta = json.load(open(os.path.join(path, "module.json")))
        self.id = self.meta["id"]
        self.name = self.meta.get("name", self.id)
        if self.meta.get("api", API) > API:
            print("modules: %s wants a newer host (api %s; this is %d)" % (self.id, self.meta["api"], API), flush=True)
        self.data_dir = os.path.join(app_data, self.id)
        os.makedirs(self.data_dir, exist_ok=True)
        for f in MIGRATE.get(self.id, []):
            old, new = os.path.join(app_data, f), os.path.join(self.data_dir, f)
            if os.path.exists(old) and not os.path.exists(new):
                os.replace(old, new); print("modules: moved %s into %s" % (old, self.data_dir), flush=True)

    def scene_dir(self, conf):
        """The scene's folder: THEME from the settings if the module has it, else its default."""
        sc = self.meta.get("scene", {})
        base = os.path.join(self.dir, sc.get("dir", "scenes"))
        name = conf.get("THEME") or sc.get("default", "")
        if not os.path.isdir(os.path.join(base, name)): name = sc.get("default", name)
        return os.path.join(base, name)

    def screens(self):
        """[(spec from module.json, the screen's class)], in order; a screen that won't load is left out."""
        if self.dir not in sys.path: sys.path.insert(0, self.dir)          # (so a screen can import its own files)
        out = []
        for spec in self.meta.get("screens", []):
            path = os.path.join(self.dir, spec["file"])
            try:
                loader = importlib.util.spec_from_file_location("%s_%s" % (self.id, spec["id"]), path)
                mod = importlib.util.module_from_spec(loader); loader.loader.exec_module(mod)
                out.append((spec, getattr(mod, spec["class"])))
            except Exception as e:                                        # (one broken screen shouldn't stop the countdown)
                print("modules: %s's screen %s didn't load: %s" % (self.id, spec.get("id"), e), flush=True)
        return out


def active(conf, app_data):
    """The module vacation.conf's MODULE names (the default if that one isn't installed)."""
    name = conf.get("MODULE") or DEFAULT
    path = os.path.join(ROOT, name)
    if not os.path.isfile(os.path.join(path, "module.json")):
        print("modules: no module called %s; using %s" % (name, DEFAULT), flush=True)
        path = os.path.join(ROOT, DEFAULT)
    return Module(path, app_data)
