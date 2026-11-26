#!/usr/bin/env -S uv run -q python
"""Preview the apps on a Mac, live, without the board: the app runs here with a plain file for its
screen, and a window (App Preview, tools/preview/viewer.swift) shows that screen and turns the mouse
into the touchscreen.

    tools/preview/preview.py [APP] [--browser] [--port 8800]
    (APP: an app in apps/, e.g. castle or cruise; default castle)

The window: menus App (the apps, ⌘1..; Restart ⌘R), Time (time of day; Pretend It's… ⌘D), Data (the
app's live data ⌘L), View (actual or double size, Keep on Top ⌘T, the log ⌘J, a screenshot to the
Desktop ⌘S). Closing it stops the preview. It's built (swiftc, from the Xcode command-line tools) the
first time and whenever viewer.swift changes. --browser, or no swiftc: a page instead, at
http://localhost:8800 (the same controls).

- The real app runs: the countdown runtime (apps/countdown, on the system package's drawing library, compiled for the Mac)
  with a countdown app; its own settings and data in build/preview/data/APP.
- Mouse: press, drag and release, as on the touchscreen (press and hold for Settings).
- Save a file in the app (or the runtime) and it restarts; change fx/vacfx.c and it's recompiled first.
- The page: pick the app; freeze the time of day or pretend it's another date; run the app's
  background job (its live data: ride waits, the ships' schedules) with the Mac's network; the app's log.
- Settings > Apps opens the real app picker, and starts the app picked, here.

Needs a C compiler (cc) and zlib (the drawing library), and Pillow (the Scene Builder).
"""
import collections, fcntl, hashlib, http.server, json, os, shutil, signal, socketserver, subprocess, sys, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
APPS = os.path.join(REPO, "apps")
RUNTIME = os.path.join(APPS, "countdown")
SYSTEM = os.path.join(APPS, "system")          # (the drawing library, Settings, the picker)
STATE = os.path.join(REPO, "build", "preview")
TRIALS = os.path.join(REPO, "build", "trial")              # scenes being tried (photo_scene.py --try): TRIALS/<app>/current
FB = os.path.join(STATE, "fb.raw")
PIPE = os.path.join(STATE, "touch.pipe")
LIB = os.path.join(STATE, "libvacfx.dylib")
PICK_REQUEST = os.path.join(STATE, "pick-request")
DEVICE_REQUEST = os.path.join(STATE, "device-request")
SWITCH_REQUEST = os.path.join(STATE, "switch-request")
VIEWER_SRC = os.path.join(HERE, "viewer.swift")
VIEWER = os.path.join(STATE, "App Preview")
W, H = 800, 480


def manifest(app):
    try: return json.load(open(os.path.join(APPS, app, "app.json")))
    except (OSError, ValueError): return {}


def conf_value(path, key):
    """KEY=value from a settings file (defaults.conf, countdown.conf), or None."""
    try:
        for line in open(path):
            if line.startswith(key + "="): return line.split("=", 1)[1].strip()
    except OSError: pass
    return None


def set_conf_values(path, values):
    """Those KEY=value lines in a settings file, changed in place (or added); a file that isn't there, left."""
    try: lines = open(path).read().splitlines()
    except OSError: return
    left = dict(values)
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0]
        if "=" in line and k in left: lines[i] = "%s=%s" % (k, left.pop(k))
    lines += ["%s=%s" % kv for kv in left.items()]
    with open(path + ".tmp", "w") as f: f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)


def ship_names():
    """The ships the ship map knows (the runtime's ships/fetch.py SHIPS)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ships_fetch_names", os.path.join(RUNTIME, "ships", "fetch.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.SHIPS.keys()


def apps():
    """The apps that can be previewed: [(id, name)]."""
    out = []
    for d in sorted(os.listdir(APPS)):
        m = manifest(d)
        if m and m.get("kind") != "runtime" and os.path.exists(os.path.join(APPS, d, "run")):
            out.append((d, m.get("name", d)))
    return sorted(out, key=lambda a: a[1].lower())


def newest(*dirs):
    """The newest change in these folders (not caches), for reloading."""
    t = 0
    for top in dirs:
        for d, sub, fs in os.walk(top):
            sub[:] = [x for x in sub if x not in ("__pycache__", "tools", ".git")]
            for f in fs:
                if f.endswith((".pyc", ".dylib", ".so")) or f.startswith("."): continue
                try: t = max(t, os.path.getmtime(os.path.join(d, f)))
                except OSError: pass
    return t


def current_trial(app):
    """The scene being tried for this app (photo_scene.py --try), if any: its folder."""
    try: name = open(os.path.join(TRIALS, app, "current")).read().strip()
    except OSError: return None
    d = os.path.join(TRIALS, app, name, "scene")
    return d if name and os.path.isdir(d) else None


class Preview:
    def __init__(self, app):
        self.app = app
        self.hour, self.now, self.service_on = "", "", False
        self.live_state = {}
        self.target, self.remote = "local", None          # (the Controls panel: this Mac's preview, or the device over USB: remote.py)
        self.builder_busy, self.builder_error, self.builder_again = "", "", None
        self.install_line = ""
        self.lock_busy = threading.Lock()
        self.live(hour=None)
        self.proc = self.svc = None
        self.log = collections.deque(maxlen=400)
        self.lock = threading.RLock()
        self.picking = False
        self.stamp = 0
        os.makedirs(STATE, exist_ok=True)
        if not os.path.exists(FB) or os.path.getsize(FB) != W * H * 4:
            with open(FB, "wb") as f: f.write(b"\0" * (W * H * 4))
        if not os.path.exists(PIPE): os.mkfifo(PIPE)
        # (a reader of our own, so the pipe can be written to between apps; what's queued is dropped)
        self.drain = os.open(PIPE, os.O_RDONLY | os.O_NONBLOCK)
        self.pipe = os.open(PIPE, os.O_WRONLY | os.O_NONBLOCK)

    def say(self, *a): self.log.append("preview: " + " ".join(str(x) for x in a)); print("preview:", *a, flush=True)

    # ---------------------------------------------------------------- building
    def build_lib(self):
        src = os.path.join(SYSTEM, "fx", "vacfx.c")
        if os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(src): return True
        r = subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", LIB, src, "-lz"], capture_output=True, text=True)
        if r.returncode: self.say("compiling the drawing library failed:\n" + r.stderr[-1500:]); return False
        self.say("compiled the drawing library"); return True

    # ---------------------------------------------------------------- running
    def env(self, app):
        e = dict(os.environ, APP_DATA=os.path.join(STATE, "data", app), APP_PICKER=os.path.join(HERE, "pick"),
                 APP_DEVICE=os.path.join(HERE, "device"), APP_SWITCH=os.path.join(HERE, "switch"),
                 PICKER_APPS=APPS, PICKER_DATA=os.path.join(STATE, "data"), PICKER_CURRENT=app,
                 PREVIEW_DIR=STATE, PYTHONUNBUFFERED="1")
        os.makedirs(e["APP_DATA"], exist_ok=True)
        trial = current_trial(app)
        if trial: e["VACATION_SCENE_DIR"] = trial
        return e

    def command(self, app):
        m = manifest(app)
        e = self.env(app)
        if m.get("runtime") == "countdown":
            if not self.build_lib(): return None
            e.update(VACATION_APP=os.path.join(APPS, app), VACATION_LIB=LIB, VACATION_FB=FB, VACATION_TOUCH_PIPE=PIPE)
            # (the time of day: live.json, which the app follows as it runs)
            if self.now: e["VACATION_NOW"] = self.now
            return [sys.executable, os.path.join(RUNTIME, "vacation.py")], e
        self.say("%s: don't know how to preview it here" % app); return None

    def reader(self, proc, tag):
        for line in iter(proc.stdout.readline, ""):
            self.log.append(tag + line.rstrip("\n"))

    def spawn(self, cmd, env, cwd, tag):
        p = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, start_new_session=True)
        threading.Thread(target=self.reader, args=(p, tag), daemon=True).start()
        return p

    def kill(self, p):
        if p and p.poll() is None:
            try: os.killpg(p.pid, signal.SIGTERM)
            except OSError: pass
            try: p.wait(3)
            except subprocess.TimeoutExpired:
                try: os.killpg(p.pid, signal.SIGKILL)
                except OSError: pass

    def stop(self):
        with self.lock:
            self.kill(self.proc); self.kill(self.svc); self.proc = self.svc = None

    def start(self, app=None):
        with self.lock:
            self.stop()
            if app: self.app = app
            if self.target == "remote" and self.remote: self.remote.switch_app(self.app)     # (Remote: the device follows)
            try:
                while os.read(self.drain, 65536): pass               # (taps meant for the last app)
            except (BlockingIOError, OSError): pass
            run = self.command(self.app)
            if not run: return
            cmd, env = run
            self.say("starting %s" % self.app)
            self.proc = self.spawn(cmd, env, os.path.join(APPS, self.app), "")
            svc = os.path.join(APPS, self.app, "service")
            if self.service_on and os.path.exists(svc):
                self.svc = self.spawn(["sh", svc], dict(env, APP_NETWORK="1"), os.path.join(APPS, self.app), "service: ")
                self.say("started its service (with the Mac's network)")
            self.stamp = newest(os.path.join(APPS, self.app), RUNTIME, SYSTEM, os.path.join(TRIALS, self.app))

    def pick(self):
        """Settings > Apps: the real picker, then the app picked (or the same one again)."""
        with self.lock:
            self.picking = True
            self.stop()
        if not self.build_lib(): self.picking = False; return
        e = dict(self.env("countdown"), PICKER_APPS=APPS, PICKER_DATA=os.path.join(STATE, "data"), PICKER_CURRENT=self.app,
                 VACATION_LIB=LIB, VACATION_FB=FB, VACATION_TOUCH_PIPE=PIPE)
        self.say("the app picker")
        r = subprocess.run([sys.executable, os.path.join(SYSTEM, "picker.py")], env=e, capture_output=True, text=True)
        if r.stderr.strip(): self.log.extend(r.stderr.strip().splitlines())
        picked = r.stdout.strip()
        self.picking = False
        self.start(picked or self.app)

    def device(self):
        """Settings > Device ›: the real device settings, then the same app again."""
        with self.lock:
            self.picking = True
            self.stop()
        if not self.build_lib(): self.picking = False; return
        e = dict(self.env("countdown"), PICKER_APPS=APPS, PICKER_DATA=os.path.join(STATE, "data"), PICKER_CURRENT=self.app,
                 VACATION_LIB=LIB, VACATION_FB=FB, VACATION_TOUCH_PIPE=PIPE)
        self.say("device settings")
        r = subprocess.run([sys.executable, os.path.join(SYSTEM, "device.py")], env=e, capture_output=True, text=True)
        self.log.extend((r.stdout + r.stderr).strip().splitlines()[-20:])
        self.picking = False
        self.start()

    def watch(self):
        """Restart the app when its files change, or when it exits (as the board does); the picker on request."""
        while True:
            time.sleep(0.5)
            if os.path.exists(PICK_REQUEST):
                os.remove(PICK_REQUEST); threading.Thread(target=self.pick, daemon=True).start(); continue
            if os.path.exists(SWITCH_REQUEST):                       # (the in-app picker: another app)
                app = open(SWITCH_REQUEST).read().strip(); os.remove(SWITCH_REQUEST)
                if app in dict(apps()): threading.Thread(target=self.start, args=(app,), daemon=True).start(); continue
            if os.path.exists(DEVICE_REQUEST):
                os.remove(DEVICE_REQUEST); threading.Thread(target=self.device, daemon=True).start(); continue
            if self.picking: continue
            with self.lock:
                if self.proc is None: continue
                if newest(os.path.join(APPS, self.app), RUNTIME, SYSTEM, os.path.join(TRIALS, self.app)) > self.stamp:
                    self.say("files changed: restarting"); self.start(); continue
                if self.proc.poll() is not None:
                    self.say("%s exited (status %s): starting it again" % (self.app, self.proc.returncode))
                    time.sleep(1.5); self.start()

    def live(self, **kw):
        """The live controls the app follows as it runs (countdown runtime: PREVIEW_DIR/live.json)."""
        self.live_state.update(kw)
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "live.json.tmp"), "w") as f: json.dump(self.live_state, f)
        os.replace(os.path.join(STATE, "live.json.tmp"), os.path.join(STATE, "live.json"))

    # ---------------------------------------------------------------- the Scene Builder (builder.html)
    def themegen(self):
        sys.path.insert(0, os.path.join(REPO, "tools", "themegen"))
        import photo_scene
        return photo_scene

    def busy(self, what, fn, again_ok=False, limit=120):
        """A slow step (making a scene from a photo: seconds) in the background; the page shows it. again_ok:
        a redo that may come while another runs (a paint stroke's: the stroke is saved already): it runs once
        more when that one's done, rather than being refused (quick strokes would seem to vanish).
        limit: seconds it may take; past that it's given up on, the page says so and the builder is free again
        (a stuck step can't hang it: Python can't stop the thread, but nothing waits for it any more). Any
        error, even one that would end a thread (SystemExit), is reported."""
        with self.lock_busy:
            if self.builder_busy:
                if again_ok: self.builder_again = (what, fn); return {"ok": True, "queued": True}
                return {"error": "busy: " + self.builder_busy}
            self.builder_busy, self.builder_error = what, ""
            self.job = job = getattr(self, "job", 0) + 1
        def give_up():
            with self.lock_busy:
                if self.job != job or not self.builder_busy: return
                self.job += 1; self.builder_again = None
                self.builder_error = "%s took over %d seconds and was given up: something in it is stuck (if the builder misbehaves, quit and reopen the preview)" % (self.builder_busy, limit)
                self.builder_busy = ""
            self.say("builder: " + self.builder_error)
        timer = threading.Timer(limit, give_up); timer.daemon = True; timer.start()
        def run(what, fn):
            nonlocal timer
            while True:
                try: fn()
                except BaseException as e:                                # (SystemExit too: an error, not a hang)
                    with self.lock_busy:
                        if self.job == job: self.builder_error = "%s: %s" % (what, e or type(e).__name__)
                    self.say("builder: %s: %s" % (what, e or type(e).__name__))
                timer.cancel()
                with self.lock_busy:
                    if self.job != job: return                            # (given up on: the builder has moved on)
                    if not self.builder_again: self.builder_busy = ""; return
                    (what, fn), self.builder_again = self.builder_again, None; self.builder_busy = what
                timer = threading.Timer(limit, give_up); timer.daemon = True; timer.start()
        threading.Thread(target=run, args=(what, fn), daemon=True).start()
        return {"ok": True}

    def photo_work(self):
        """The work folder of the scene showing (a trial's, or the app's own), or None."""
        if manifest(self.app).get("runtime") != "countdown": return None
        ps = self.themegen(); cur = current_trial(self.app)
        return ps.dirs(self.app, os.path.basename(os.path.dirname(cur)) if cur else "")[1]

    def photo_key(self):
        """Changes when the scene showing's original photo does (the window fetches it again): "" if none."""
        work = self.photo_work()
        try: conf = json.load(open(os.path.join(work, "scene.json")))
        except (OSError, ValueError, TypeError): return ""
        p = conf.get("photo") or ""
        if not os.path.exists(p) or conf.get("plates_fixed"): return ""
        return "%s|%s|%s" % (p, os.path.getmtime(p), conf.get("crop"))

    def photo_jpeg(self):
        """The original photo, cut as the scene is, as a JPEG (cached by its key)."""
        key = self.photo_key()
        if not key: return None
        if getattr(self, "_photo", (None,))[0] != key:
            import io
            img = self.themegen().original(self.photo_work())
            if img is None: self._photo = (key, None)
            else: b = io.BytesIO(); img.save(b, "JPEG", quality=90); self._photo = (key, b.getvalue())
        return self._photo[1]

    def builder_state(self):
        app = self.app; m = manifest(app)
        out = {"app": app, "name": m.get("name", app), "countdown": m.get("runtime") == "countdown", "stay": bool(self.live_state.get("stay")),
               "busy": self.builder_busy, "error": self.builder_error, "trials": [], "showing": "", "kept": False, "conf": {},
               "install": self.install_line,
               "apps": [[a, n] for a, n in apps() if manifest(a).get("runtime") == "countdown"]}
        if not out["countdown"]: return out
        ps = self.themegen()
        out["trials"] = [{"name": t["name"], "current": t["current"]} for t in ps.trials(app)]
        cur = current_trial(app)
        out["showing"] = os.path.basename(os.path.dirname(cur)) if cur else ""
        _, work = ps.dirs(app, out["showing"])
        try: out["conf"] = json.load(open(os.path.join(work, "scene.json")))
        except (OSError, ValueError): out["conf"] = {}
        out["kept"] = os.path.exists(os.path.join(ps.app_dirs(app)[1], "scene.json"))
        scene, _ = ps.dirs(app, out["showing"])
        try: th = json.load(open(os.path.join(scene, "theme.json")))
        except (OSError, ValueError): th = {}
        out["foam"] = th.get("foam") or {}
        out["fireflies"], out["mist"], out["fireworks"] = th.get("fireflies") or {}, th.get("mist") or {}, th.get("fireworks", True) is not False
        out["smoke"], out["birds"] = th.get("smoke") or {}, "birds" in th.get("effects", []) or "gulls" in th.get("effects", [])
        out["screens"] = self.screens_for_builder(app, m)               # (the app's screens, and the types there are)
        out["ship_names"] = list(ship_names())
        sys.path.insert(0, RUNTIME); import screens as screen_types
        out["screen_types"] = sorted(screen_types.TYPES)
        scene, _ = ps.dirs(app, out["showing"])
        try: theme = json.load(open(os.path.join(scene, "theme.json")))
        except (OSError, ValueError): theme = {}
        out["cards"], out["horizon"] = theme.get("cards") or {}, theme.get("horizon")
        out["card_size"] = [ps.scene_pack.CW, ps.scene_pack.CH]
        try:                                                             # (the trip's date: "see it with 3 digits")
            for line in open(os.path.join(STATE, "data", app, "countdown.conf")):
                if line.startswith(("TRIP_DATE=", "SAIL_DATE=")) and line.split("=", 1)[1].strip(): out["trip"] = line.split("=", 1)[1].strip()
        except OSError: pass
        try: out["lights"] = len(json.load(open(os.path.join(work, "twinkle_points.json"))))
        except (OSError, ValueError): out["lights"] = 0
        try: out["window_edits"] = len(json.load(open(os.path.join(work, "windows_edits.json"))))
        except (OSError, ValueError): out["window_edits"] = 0
        out["windows_found"] = os.path.exists(os.path.join(work, "windows_base.png"))
        try: out["water_edits"] = len(json.load(open(os.path.join(work, "water_edits.json"))))
        except (OSError, ValueError): out["water_edits"] = 0
        out["water_found"] = os.path.exists(os.path.join(work, "water_base.png"))
        return out

    def sheet(self, name):
        ps = self.themegen()
        scene, _ = ps.dirs(self.app, name)
        p = os.path.join(scene, "preview.png")
        return p if os.path.exists(p) else None

    def upload(self, filename, data, orb):
        """A photo dropped on the builder: kept in build/trial/APP/uploads/, made into a trial (with the
        lights on a sphere found in it, if orb is "auto")."""
        if not data: return {"error": "no photo"}
        name = os.path.basename(filename) or "photo.jpg"
        d = os.path.join(TRIALS, self.app, "uploads"); os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "wb") as f: f.write(data)
        ps = self.themegen()
        return self.busy("making a scene from %s" % name, lambda: ps.try_photo(self.app, path, "auto" if orb == "auto" else None),
                         limit=420)                              # (the first one may fetch the segmentation model: ~100 MB)

    def install(self, c):
        """The app on the device (tools/board/deploy.py, over USB): its kept scene, with the system and the
        countdown runtime it runs on (unsigned: only what changed is copied); {"signed": true, "passphrase":
        "..."} packed and signed (the passphrase to deploy.py on its stdin, nowhere else). Then it's the app
        that runs (deploy.py --use). Its output in the log; the last line in the Scene Builder."""
        app = self.app
        names = ["system", "countdown", app] if c.get("runtime", True) and manifest(app).get("runtime") == "countdown" else [app]
        cmd = [sys.executable, os.path.join(REPO, "tools", "board", "deploy.py")]
        if c.get("signed"): cmd += ["--signed"] + (["--passphrase-stdin"] if c.get("passphrase") else [])
        cmd += ["--use", app]                                            # (installed: the app that runs, now and at every boot)
        cmd += names
        def run():
            self.install_line = "starting"
            p = subprocess.Popen(cmd, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if c.get("signed") and c.get("passphrase"): p.stdin.write(c["passphrase"] + "\n")
            p.stdin.close()
            for line in p.stdout:
                line = line.rstrip()
                if line and not line.lstrip().endswith("%"): self.say("install: " + line); self.install_line = line
            if p.wait(): raise RuntimeError(self.install_line or "it failed")
            self.install_line = "installed%s" % (" (signed)" if c.get("signed") else "")
        self.install_line = ""
        return self.busy("installing %s on the device" % app, run)

    def parks(self):
        """Every park ThemeParks.wiki has, by destination: [{"dest", "parks": [{"id", "name"}]}] (fetched once)."""
        if not getattr(self, "_parks", None):
            sys.path.insert(0, os.path.join(REPO, "tools", "apps")); import new as newapp
            ds = newapp.get("destinations")["destinations"]
            self._parks = sorted(({"dest": d["name"], "parks": sorted(({"id": p["id"], "name": p["name"]} for p in d["parks"]), key=lambda p: p["name"])}
                                  for d in ds if d.get("parks")), key=lambda d: d["dest"])
        return self._parks

    @staticmethod
    def places(q):
        """The places a name could mean (Open-Meteo's geocoding): [{"name": "Springfield, Illinois, United States", "lat", "lon"}]."""
        if not q.strip(): return []
        u = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": q.strip(), "count": 8, "language": "en", "format": "json"})
        req = urllib.request.Request(u, headers={"User-Agent": "licheepi-vacation-countdown"})
        with urllib.request.urlopen(req, timeout=20) as r: hits = json.load(r).get("results") or []
        return [{"name": ", ".join(v for v in (h.get("name"), h.get("admin1"), h.get("country")) if v),
                 "lat": round(h["latitude"], 4), "lon": round(h["longitude"], 4)} for h in hits]

    def screens_for_builder(self, app, m):
        """The app's screens as the builder edits them: a wait-times screen with its park's name and tonight's
        show (app.json "park"), a ship map with the app's own ship (defaults.conf SHIP)."""
        park = m.get("park") or {}
        pname = park.get("name", "")
        if not pname and park.get("id"):
            try: pname = json.load(open(os.path.join(APPS, app, "waits_example.json"))).get("park", "")
            except (OSError, ValueError): pass
        ship = conf_value(os.path.join(APPS, app, "defaults.conf"), "SHIP") or "Disney Dream"
        out = []
        for s in m.get("screens", []):
            if s.get("type") == "waits": s = dict(s, park=pname, park_id=park.get("id", ""))
            elif s.get("type") == "ships": s = dict(s, ship=ship)
            out.append(s)
        return out

    def set_screens(self, screens):
        """The app's screens (app.json "screens") as the builder has them: known types only; a weather screen
        with a place but no lat/lon looked up by name (tools/apps/new.py), and an example of its weather
        fetched if the app hasn't one; the app's service the shared fetcher loop if any of them fetch."""
        sys.path.insert(0, os.path.join(RUNTIME)); import screens as screen_types
        sys.path.insert(0, os.path.join(REPO, "tools", "apps")); import new as newapp
        d = os.path.join(APPS, self.app); p = os.path.join(d, "app.json")
        meta = json.load(open(p)); out = []
        def look_up(fn, text):                                           # (new.py's: they exit when there's no match)
            try: return fn(text)
            except SystemExit as e: raise ValueError(str(e).replace("new: ", ""))
        for s in screens:
            s = dict(s)
            if s.get("type") == "waits":                                 # (the park: the app's, app.json "park"; looked up by name)
                ptext = (s.pop("park", "") or "").strip(); s.pop("show", None)
                pid = (s.pop("park_id", "") or "").strip()
                park = dict(meta.get("park") or {})
                if not ptext and not pid: raise ValueError("a wait-times screen needs a park (pick one)")
                if pid:                                                  # (picked from the list: no lookup)
                    if pid != park.get("id"):
                        with open(os.path.join(d, "waits_example.json"), "w") as f: json.dump(newapp.example_waits(pid, ptext), f, indent=1)
                    park.update(id=pid, name=ptext or park.get("name", ""))
                elif ptext != park.get("name") or not park.get("id"):
                    pid, pname = look_up(newapp.find_park, ptext)
                    if pid != park.get("id"):
                        with open(os.path.join(d, "waits_example.json"), "w") as f: json.dump(newapp.example_waits(pid, pname), f, indent=1)
                    park.update(id=pid, name=pname)
                park.pop("show", None)
                meta["park"] = park
            if s.get("type") == "ships":                                 # (the app's own ship: SHIP, and the one the map follows)
                ship = s.pop("ship", "")
                if ship in ship_names():
                    for f in (os.path.join(d, "defaults.conf"), os.path.join(STATE, "data", self.app, "countdown.conf")):
                        set_conf_values(f, {"SHIP": ship, "MAP_SHIP": ship})
            s = {k: v for k, v in s.items() if v not in (None, "")}
            if s.get("type") not in screen_types.TYPES:
                if s.get("file"): out.append(s)                       # (a screen of the app's own: as it was)
                continue
            if s["type"] == "weather" and s.get("place") and not ("lat" in s and "lon" in s and s.get("looked_up") == s["place"]):
                name, lat, lon = look_up(newapp.find_place, s["place"]); s.update(place=name, lat=lat, lon=lon, looked_up=name)
                if not os.path.exists(os.path.join(d, "weather_example.json")):
                    with open(os.path.join(d, "weather_example.json"), "w") as f: json.dump(newapp.example_weather(s, d), f, indent=1)
            if isinstance(s.get("secs"), str) and s["secs"].isdigit(): s["secs"] = int(s["secs"])
            out.append(s)
        meta["screens"] = out
        if any(s.get("type") for s in out): meta["api"] = max(meta.get("api", 2), 4)
        with open(p + ".tmp", "w") as f: json.dump(meta, f, indent=2); f.write("\n")
        os.replace(p + ".tmp", p)
        svc = os.path.join(d, "service")
        if screen_types.plan(p) and not (os.path.exists(svc) and "screens.sh" in open(svc).read()):
            with open(svc, "w") as f: f.write("#!/bin/sh\n# %s's background job: what its screens show (the countdown runtime's shared fetcher loop).\nexec ../countdown/screens.sh\n" % meta.get("name", self.app))
            os.chmod(svc, 0o755)
        self.say("screens: %s" % ", ".join(s.get("type") or s.get("id", "?") for s in out))

    def new_app(self, c):
        """A new countdown app (tools/apps/new.py: a placeholder scene, an icon, a splash; a park's waits or a
        place's weather if given), then it's the app shown: drop a photo on it next."""
        aid = "".join(ch if ch.isalnum() else "-" for ch in (c.get("id") or c.get("title") or "").lower()).strip("-")
        while "--" in aid: aid = aid.replace("--", "-")
        if not aid or not (c.get("title") or "").strip(): return {"error": "a new app needs a name"}
        if os.path.exists(os.path.join(APPS, aid)): return {"error": "there's an app called %s already" % aid}
        cmd = [sys.executable, os.path.join(REPO, "tools", "apps", "new.py"), aid, "--name", c["title"].strip(),
               "--date-label", (c.get("date_label") or "Trip day").strip()]
        if (c.get("park") or "").strip(): cmd += ["--park", c["park"].strip()]
        if (c.get("weather") or "").strip(): cmd += ["--weather", c["weather"].strip(), "--units", "C" if c.get("units") == "C" else "F"]
        def make():
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.say("new app: " + (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "new app: done")
            if r.returncode != 0:
                if os.path.isdir(os.path.join(APPS, aid)) and not os.path.exists(os.path.join(APPS, aid, "scenes")):
                    shutil.rmtree(os.path.join(APPS, aid))               # (half made: so it can be tried again)
                raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "new.py failed")
            self.start(aid)
        return self.busy("making the app %s" % c["title"].strip(), make)

    def builder_do(self, c):
        if c.get("action") == "new_app": return self.new_app(c)
        ps, app, act = self.themegen(), self.app, c.get("action")
        if "name" in c: name = c["name"]
        else: cur = current_trial(app); name = os.path.basename(os.path.dirname(cur)) if cur else ""   # (the scene showing)
        if act == "use": ps.set_current(app, name); return {"ok": True}
        if act == "keep": return self.busy("keeping %s" % name, lambda: ps.keep_trial(app, name))
        if act == "delete": ps.delete_trial(app, name); return {"ok": True}
        if act == "orb":                                                # (the lights on a sphere: found, given, or none)
            mode = c.get("mode")
            orb = "auto" if mode == "auto" else False if mode == "off" else tuple(int(v) for v in mode)
            return self.busy("finding the lights" if orb else "taking the lights off", lambda: ps.rebuild(app, name, orb))
        if act == "layout":                                             # (the cards' place; the horizon: slower, a repack)
            cards = c.get("cards"); hz = c.get("horizon")
            if c.get("card_style"): return self.busy("drawing the cards", lambda: ps.set_layout(app, name, card_style=c["card_style"]))
            if hz is None: ps.set_layout(app, name, cards=cards); return {"ok": True}
            return self.busy("setting the horizon", lambda: ps.set_layout(app, name, cards=cards, horizon=hz))
        if act == "effect":                                             # (smoke, birds: at once)
            ps.set_effect(app, name, c["key"], c.get("value")); return {"ok": True}
        if act == "smoke_add":                                          # (a click on the picture: a smoke source there)
            scene, work = ps.dirs(app, name)
            try: sm = json.load(open(os.path.join(work, "scene.json"))).get("smoke") or {}
            except (OSError, ValueError): sm = json.load(open(os.path.join(scene, "theme.json"))).get("smoke") or {}
            sm = dict({"scale": 0.8, "wind": 0, "rate": 4}, **sm); sm["points"] = (sm.get("points") or [])[:7] + [[int(c["x"]), int(c["y"])]]
            ps.set_effect(app, name, "smoke", sm); return {"ok": True, "smoke": len(sm["points"])}
        if act == "foam_add":                                           # (a click on the picture: foam there, at the size chosen)
            scene, work = ps.dirs(app, name)
            try: fo = json.load(open(os.path.join(work, "scene.json"))).get("foam") or {}
            except (OSError, ValueError): fo = json.load(open(os.path.join(scene, "theme.json"))).get("foam") or {}
            fo = dict({"amount": 1.0, "flow": "still", "size": 12}, **fo)
            r = int(c.get("r") or fo.get("size", 12))
            fo["points"] = (fo.get("points") or [])[:15] + [[int(c["x"]), int(c["y"]), r]]
            ps.set_effect(app, name, "foam", fo); return {"ok": True, "foam": len(fo["points"])}
        if act in ("fireflies_add", "mist_box"):                       # (a click: fireflies there; a box: the mist's)
            scene, work = ps.dirs(app, name)
            key = "fireflies" if act == "fireflies_add" else "mist"
            try: cur = json.load(open(os.path.join(work, "scene.json"))).get(key) or {}
            except (OSError, ValueError): cur = json.load(open(os.path.join(scene, "theme.json"))).get(key) or {}
            if key == "fireflies":
                cur = dict({"amount": 1.0, "size": 40}, **cur)
                cur["points"] = (cur.get("points") or [])[:15] + [[int(c["x"]), int(c["y"]), int(c.get("r") or cur.get("size", 40))]]
            else:
                cur = dict({"amount": 1.0, "when": "dawn"}, **cur); cur["box"] = [int(v) for v in c["box"]]
            ps.set_effect(app, name, key, cur); return {"ok": True}
        if act == "screens":                                            # (the app's screens: app.json, written)
            return self.busy("setting the screens", lambda: self.set_screens(c.get("screens") or []))
        if act == "screen_now":
            i = int(c.get("index", 0)); self.live(screen=i, screen_go=self.live_state.get("screen_go", 0) + 1, screen_at=time.time()); return {"ok": True}
        if act == "show":
            return self.busy("setting the show", lambda: ps.set_show(app, name, c.get("program") or [], c.get("secs", 12)))
        return {"error": "no action %s" % act}

    def windows(self, c): return self.region("windows", c)
    def water(self, c): return self.region("water", c)

    def region(self, kind, c):
        """Painting a region of the scene on show (a photo's: trial or the app's): "windows" (the glass that
        glows at night) or "water" (where it ripples). {"paint": [[x, y, r], ...]}, {"erase": [...]} (one drag),
        {"rect": [x0, y0, x1, y1]}, {"undo": true}; {"auto": true} (found in the photo: the base the painting
        goes over), {"clear_auto": true}; windows {"colour": [r, g, b]}; water {"strength": s, "speed": v}.
        Redone in the background (a second or two)."""
        ps = self.themegen()
        cur = current_trial(self.app)
        scene, work = ps.dirs(self.app, os.path.basename(os.path.dirname(cur)) if cur else "")
        if not os.path.exists(os.path.join(work, "scene.json")):
            return {"error": "painting works on a scene made from a photo (drop one on the Scene Builder)"}
        redo = ps.rewindow if kind == "windows" else ps.rewater
        what = "lighting the windows" if kind == "windows" else "laying the water"
        report = (lambda n: self.say("windows: %d" % n)) if kind == "windows" else (lambda n: self.say("water: %s%% of the screen" % n))
        if kind == "windows" and c.get("colour"):
            return self.busy(what, lambda: report(ps.set_window_light(work, scene, c["colour"])))
        if kind == "water" and ("strength" in c or "speed" in c):
            return self.busy(what, lambda: report(ps.set_water(work, scene, c.get("strength"), c.get("speed"))))
        if c.get("auto"):
            find = ps.find_windows_into if kind == "windows" else ps.find_water_into
            return self.busy("finding " + kind, lambda: self.say("%s: found: %s" % (kind, find(work, scene))))
        if c.get("clear_auto"):
            clear = ps.clear_found_windows if kind == "windows" else ps.clear_found_water
            return self.busy("clearing the found " + kind, lambda: report(clear(work, scene)))
        path = os.path.join(work, kind + "_edits.json")
        try: edits = json.load(open(path))
        except (OSError, ValueError): edits = []
        if c.get("undo") and edits: edits.pop()
        elif c.get("paint"): edits.append({"paint": [[int(x), int(y), int(r)] for x, y, r in c["paint"]]})
        elif c.get("erase"): edits.append({"erase": [[int(x), int(y), int(r)] for x, y, r in c["erase"]]})
        elif c.get("rect"): edits.append({"rect": [int(v) for v in c["rect"]]})
        elif c.get("group") and kind == "windows": edits.append({"group": [int(v) for v in c["group"]]})
        elif c.get("behind") and kind == "windows": edits.append({"behind": [int(v) for v in c["behind"]]})
        elif c.get("frame") and kind == "windows": edits.append({"frame": [[int(x), int(y), int(r)] for x, y, r in c["frame"]]})
        else: return {"error": "nothing to do"}
        json.dump(edits, open(path, "w"))
        r = self.busy(what, lambda: report(redo(work, scene)), again_ok=True)   # (strokes in a row: each saved, redone after)
        return dict(r, edits=len(edits))

    def lights(self, c):
        """Editing the lights of the scene on show: {"erase": [[x, y, r], ...]} (one drag), {"add": [[x, y]]}
        (a click), or {"undo": true} (the last edit back). On the photo being tried (photo_scene.py --try),
        else on the app's own scene (made by photo_scene.py: tools/themegen/work/APP). The lights are redone
        (work/edits.json), and the app restarts with them."""
        trial = current_trial(self.app)
        if trial: work, scene = os.path.join(os.path.dirname(trial), "work"), trial
        else:
            m = manifest(self.app); sc = m.get("scene") or {}
            work = os.path.join(REPO, "tools", "themegen", "work", self.app)
            scene = os.path.join(APPS, self.app, sc.get("dir", "scenes"), sc.get("default", ""))
        if not os.path.exists(os.path.join(work, "twinkle_found.json")):
            return {"error": "this scene has no lights made from a photo (photo_scene.py PHOTO %s --try --orb auto)" % self.app}
        path = os.path.join(work, "edits.json")
        try: edits = json.load(open(path))
        except (OSError, ValueError):                                    # (rub-outs from before additions)
            try: edits = [{"erase": g} for g in json.load(open(os.path.join(work, "erase_groups.json")))]
            except (OSError, ValueError): edits = []
        if c.get("undo") and edits: edits.pop()
        elif c.get("erase"): edits.append({"erase": [[int(x), int(y), int(r)] for x, y, r in c["erase"]]})
        elif c.get("add"): edits.append({"add": [[int(x), int(y)] for x, y in c["add"]]})
        json.dump(edits, open(path, "w"))
        sys.path.insert(0, os.path.join(REPO, "tools", "themegen"))
        import photo_scene
        n = photo_scene.relight(work, scene)
        self.say("lights: %s (%d edits)" % (n, len(edits)))
        return {"lights": n, "edits": len(edits)}

    def touch(self, line):
        try: os.write(self.pipe, (line.strip() + "\n").encode())
        except (BlockingIOError, OSError): pass


def serve(pv, port):
    page = open(os.path.join(HERE, "index.html"), "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def send(self, code, body, kind="application/json", headers=()):
            self.send_response(code)
            self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in headers: self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.path == "/": return self.send(200, page, "text/html; charset=utf-8")
            if self.path == "/builder":                                 # (the Scene Builder: the window's side panel)
                return self.send(200, open(os.path.join(HERE, "builder.html"), "rb").read(), "text/html; charset=utf-8")
            if self.path.startswith("/builder/state"): return self.send(200, json.dumps(pv.builder_state()).encode())
            if self.path.startswith("/builder/parks") or self.path.startswith("/builder/places"):   # (the screens' pickers)
                try:
                    if self.path.startswith("/builder/parks"): out = pv.parks()
                    else: out = pv.places(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0])
                except Exception as e: out = {"error": "couldn't look it up: %s" % e}
                return self.send(200, json.dumps(out).encode())
            if self.path.startswith("/builder/outline"):               # (what was found, to flash over the picture)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                ps = pv.themegen(); cur = current_trial(pv.app)
                _, work = ps.dirs(pv.app, os.path.basename(os.path.dirname(cur)) if cur else "")
                return self.send(200, ps.found_outline(work, q.get("kind", ["sky"])[0]), "image/png")
            if self.path.startswith("/builder/sheet"):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                path = pv.sheet(q.get("name", [""])[0])
                if not path: return self.send(404, b"{}")
                return self.send(200, open(path, "rb").read(), "image/png")
            if self.path == "/frame":
                data = open(FB, "rb").read()
                tag = hashlib.blake2b(data, digest_size=8).hexdigest()
                if self.headers.get("If-None-Match") == tag:
                    self.send_response(304); self.send_header("ETag", tag); self.end_headers(); return
                return self.send(200, data, "application/octet-stream", [("ETag", tag)])
            if self.path.startswith("/state"):
                state = {"app": pv.app, "apps": apps(), "hour": pv.hour, "now": pv.now, "service": pv.service_on,
                         "has_service": os.path.exists(os.path.join(APPS, pv.app, "service")),
                         "countdown": manifest(pv.app).get("runtime") == "countdown", "log": list(pv.log)[-200:],
                         "target": pv.target, "remote_note": pv.remote.note if pv.remote else "",
                         "stay": bool(pv.live_state.get("stay")), "pattern": pv.live_state.get("pattern", -1)}
                try: state["photo_key"] = pv.photo_key()
                except Exception: state["photo_key"] = ""
                return self.send(200, json.dumps(state).encode())
            if self.path.startswith("/builder/photo"):                 # (the original photo, for the window zoomed in)
                data = pv.photo_jpeg()
                return self.send(200, data, "image/jpeg") if data else self.send(404, b"{}")
            self.send(404, b"{}")

        def do_POST(self):
            if self.path.startswith("/builder/upload"): body = ""        # (binary: read below)
            else: body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
            if self.path == "/touch":
                pv.touch(body); return self.send(200, b"{}")
            if self.path.startswith("/builder/upload"):                 # (a photo, its bytes: a new trial)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                n = int(self.headers.get("Content-Length", "0"))
                return self.send(200, json.dumps(pv.upload(q.get("name", ["photo.jpg"])[0], self.rfile.read(n), q.get("orb", [""])[0])).encode())
            if self.path == "/builder/install":
                return self.send(200, json.dumps(pv.install(json.loads(body or "{}"))).encode())
            if self.path == "/builder/do":
                return self.send(200, json.dumps(pv.builder_do(json.loads(body or "{}"))).encode())
            if self.path == "/windows":                                 # (painting window lights, in the scene on show)
                return self.send(200, json.dumps(pv.windows(json.loads(body or "{}"))).encode())
            if self.path == "/water":                                   # (painting water, in the scene on show)
                return self.send(200, json.dumps(pv.water(json.loads(body or "{}"))).encode())
            if self.path == "/lights":                                  # (rubbing out or adding lights, in the scene on show)
                return self.send(200, json.dumps(pv.lights(json.loads(body or "{}"))).encode())
            if self.path == "/control":
                c = json.loads(body or "{}")
                if "target" in c:                                        # (the Controls panel: this Mac, or the device)
                    want = "remote" if c["target"] == "remote" else "local"
                    if want == "remote" and not pv.remote:
                        sys.path.insert(0, HERE); import remote; pv.remote = remote.Remote()
                    if want == "local" and pv.target == "remote": pv.remote.reset()
                    pv.target = want
                    if want == "remote": pv.remote.set(stay=False); pv.remote.switch_app(pv.app)
                    return self.send(200, b"{}")
                if c.get("panel") and pv.target == "remote":            # (the panel's controls, for the device's countdown)
                    r = pv.remote
                    if "hour" in c: r.set(hour=float(c["hour"]) if str(c["hour"]) != "" else None)
                    for k in ("fireworks", "show", "birds", "fireflies"):
                        if c.get(k): r.fire(k)
                    if "pattern" in c: r.set(pattern=int(c["pattern"]))
                    if "stay" in c: r.set(stay=bool(c["stay"]))
                    return self.send(200, b"{}")
                # live, no restart: the time of day (the slider, the Time menu), fireworks, the nightly show
                if "hour" in c: pv.hour = str(c["hour"]); pv.live(hour=float(c["hour"]) if str(c["hour"]) != "" else None)
                if c.get("fireworks"): pv.live(fireworks=pv.live_state.get("fireworks", 0) + 1)
                if c.get("birds"): pv.live(birds=pv.live_state.get("birds", 0) + 1)
                if c.get("fireflies"): pv.live(fireflies=pv.live_state.get("fireflies", 0) + 1)
                if "windows_hold" in c: pv.live(windows_hold=bool(c["windows_hold"]))
                if c.get("show"): pv.live(show=pv.live_state.get("show", 0) + 1)
                if "pattern" in c: pv.live(pattern=int(c["pattern"]))                # (the lights' show: one pattern held, or -1)
                if "stay" in c: pv.live(stay=bool(c["stay"]))                         # (stay on the scene: the app's screens wait)
                # a restart: another app, another date, the background job on or off, or Restart ({})
                if "now" in c: pv.now = str(c["now"])
                if "service" in c: pv.service_on = bool(c["service"])
                if not c or any(k in c for k in ("app", "now", "service")):
                    threading.Thread(target=pv.start, args=(c.get("app"),), daemon=True).start()
                return self.send(200, b"{}")
            self.send(404, b"{}")

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    Server(("127.0.0.1", port), Handler).serve_forever()


def viewer():
    """The window, built if it isn't, or is older than its source; None if it can't be."""
    if os.path.exists(VIEWER) and os.path.getmtime(VIEWER) >= os.path.getmtime(VIEWER_SRC): return VIEWER
    if not shutil.which("swiftc"): return None
    print("preview: building the window (once: about 20 s)", flush=True)
    os.makedirs(STATE, exist_ok=True)
    r = subprocess.run(["swiftc", "-O", "-swift-version", "5", "-o", VIEWER, VIEWER_SRC], capture_output=True, text=True)
    if r.returncode: print("preview: building the window failed:\n" + r.stderr[-1500:], flush=True); return None
    return VIEWER


def main():
    a = sys.argv[1:]
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8800
    if "--port" in a: i = a.index("--port"); del a[i:i + 2]
    browser = "--browser" in a
    a = [x for x in a if x != "--browser"]
    if any(x.startswith("-") for x in a): sys.exit(__doc__)
    app = a[0] if a else "castle"
    if app not in dict(apps()): sys.exit("no app %s to preview (%s)" % (app, ", ".join(x for x, _ in apps())))
    # one preview at a time: two would share the screen file and the touch pipe (each app drawing over the
    # other's, taps going to either)
    os.makedirs(STATE, exist_ok=True)
    lock = open(os.path.join(STATE, "lock"), "a+")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: sys.exit("a preview is already running (its window, or another preview.py): close it first")
    lock.seek(0); lock.truncate(); lock.write(str(os.getpid())); lock.flush()
    window = None if browser else viewer()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))   # (stopped: stop the app too)
    pv = Preview(app)
    pv.start()
    threading.Thread(target=pv.watch, daemon=True).start()
    threading.Thread(target=serve, args=(pv, port), daemon=True).start()
    try:
        if window:
            print("preview: the App Preview window (close it, or Ctrl-C, to stop)", flush=True)
            subprocess.run([window, "--fb", FB, "--pipe", PIPE, "--port", str(port)])
        else:
            print("preview: http://localhost:%d  (Ctrl-C to stop)" % port, flush=True)
            while True: time.sleep(3600)
    except KeyboardInterrupt: pass
    finally: pv.stop()


if __name__ == "__main__":
    main()
