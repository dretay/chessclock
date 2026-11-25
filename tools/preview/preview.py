#!/usr/bin/env python3
"""Preview the apps on a Mac, live, without the board: the app runs here with a plain file for its
screen, and a window (App Preview, tools/preview/viewer.swift) shows that screen and turns the mouse
into the touchscreen.

    tools/preview/preview.py [APP] [--browser] [--port 8800]
    (APP: castle, cruise or chess; default castle)

The window: menus App (the apps, ⌘1..; Restart ⌘R), Time (time of day; Pretend It's… ⌘D), Data (the
app's live data ⌘L), View (actual or double size, Keep on Top ⌘T, the log ⌘J, a screenshot to the
Desktop ⌘S). Closing it stops the preview. It's built (swiftc, from the Xcode command-line tools) the
first time and whenever viewer.swift changes. --browser, or no swiftc: a page instead, at
http://localhost:8800 (the same controls).

- The real app runs: the countdown runtime (apps/countdown, on the system package's drawing library, compiled for the Mac)
  with a countdown app, or the chess clock; its own settings and data in build/preview/data/APP.
- Mouse: press, drag and release, as on the touchscreen (press and hold for Settings).
- Save a file in the app (or the runtime) and it restarts; change fx/vacfx.c and it's recompiled first.
- The page: pick the app; freeze the time of day or pretend it's another date; run the app's
  background job (its live data: ride waits, the ships' schedules) with the Mac's network; the app's log.
- Settings > Apps opens the real app picker, and starts the app picked, here.

The chess clock draws with the DejaVu fonts, as on the board: they're copied once from the board's
build tree (tools/build/build.sh's licheepi-out volume), or FBCLOCK_FONTS names a folder with them.
Needs Pillow (the chess clock) and a C compiler (cc) and zlib (the countdown).
"""
import collections, fcntl, hashlib, http.server, json, os, shutil, signal, socketserver, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
APPS = os.path.join(REPO, "apps")
RUNTIME = os.path.join(APPS, "countdown")
SYSTEM = os.path.join(APPS, "system")          # (the drawing library, Settings, the picker)
STATE = os.path.join(REPO, "build", "preview")
FB = os.path.join(STATE, "fb.raw")
PIPE = os.path.join(STATE, "touch.pipe")
LIB = os.path.join(STATE, "libvacfx.dylib")
FONTS = os.environ.get("FBCLOCK_FONTS") or os.path.join(STATE, "fonts")
PICK_REQUEST = os.path.join(STATE, "pick-request")
DEVICE_REQUEST = os.path.join(STATE, "device-request")
SWITCH_REQUEST = os.path.join(STATE, "switch-request")
VIEWER_SRC = os.path.join(HERE, "viewer.swift")
VIEWER = os.path.join(STATE, "App Preview")
W, H = 800, 480


def manifest(app):
    try: return json.load(open(os.path.join(APPS, app, "app.json")))
    except (OSError, ValueError): return {}


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


class Preview:
    def __init__(self, app):
        self.app = app
        self.hour, self.now, self.service_on = "", "", False
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

    def fonts(self):
        if os.path.exists(os.path.join(FONTS, "DejaVuSans.ttf")): return True
        runner = shutil.which("container") or shutil.which("docker")
        if runner:
            os.makedirs(FONTS, exist_ok=True)
            for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
                r = subprocess.run([runner, "run", "--rm", "-v", "licheepi-out:/root/buildroot", "licheepi-nano-mybase",
                                    "cat", "/root/buildroot/output/target/usr/share/fonts/dejavu/" + f], capture_output=True)
                if r.returncode == 0 and r.stdout: open(os.path.join(FONTS, f), "wb").write(r.stdout)
        if os.path.exists(os.path.join(FONTS, "DejaVuSans.ttf")): self.say("copied the DejaVu fonts from the build tree"); return True
        self.say("the chess clock needs the DejaVu fonts: run tools/build/build.sh once, or set FBCLOCK_FONTS"); return False

    # ---------------------------------------------------------------- running
    def env(self, app):
        e = dict(os.environ, APP_DATA=os.path.join(STATE, "data", app), APP_PICKER=os.path.join(HERE, "pick"),
                 APP_DEVICE=os.path.join(HERE, "device"), APP_SWITCH=os.path.join(HERE, "switch"),
                 PICKER_APPS=APPS, PICKER_DATA=os.path.join(STATE, "data"), PICKER_CURRENT=app,
                 PREVIEW_DIR=STATE, PYTHONUNBUFFERED="1")
        os.makedirs(e["APP_DATA"], exist_ok=True)
        return e

    def command(self, app):
        m = manifest(app)
        e = self.env(app)
        if m.get("runtime") == "countdown":
            if not self.build_lib(): return None
            e.update(VACATION_APP=os.path.join(APPS, app), VACATION_LIB=LIB, VACATION_FB=FB, VACATION_TOUCH_PIPE=PIPE)
            if self.hour: e["VACATION_HOUR"] = self.hour
            if self.now: e["VACATION_NOW"] = self.now
            return [sys.executable, os.path.join(RUNTIME, "vacation.py")], e
        if app == "chess":
            if not self.fonts(): return None
            e.update(FBCLOCK_DEVICE=FB, FBCLOCK_FONTS=FONTS, FBCLOCK_TOUCH_PIPE=PIPE)
            return [sys.executable, os.path.join(APPS, "chess", "fbclock.py")], e
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
            self.stamp = newest(os.path.join(APPS, self.app), RUNTIME, SYSTEM)

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
                if newest(os.path.join(APPS, self.app), RUNTIME, SYSTEM) > self.stamp:
                    self.say("files changed: restarting"); self.start(); continue
                if self.proc.poll() is not None:
                    self.say("%s exited (status %s): starting it again" % (self.app, self.proc.returncode))
                    time.sleep(1.5); self.start()

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
            if self.path == "/frame":
                data = open(FB, "rb").read()
                tag = hashlib.blake2b(data, digest_size=8).hexdigest()
                if self.headers.get("If-None-Match") == tag:
                    self.send_response(304); self.send_header("ETag", tag); self.end_headers(); return
                return self.send(200, data, "application/octet-stream", [("ETag", tag)])
            if self.path.startswith("/state"):
                state = {"app": pv.app, "apps": apps(), "hour": pv.hour, "now": pv.now, "service": pv.service_on,
                         "has_service": os.path.exists(os.path.join(APPS, pv.app, "service")),
                         "countdown": manifest(pv.app).get("runtime") == "countdown", "log": list(pv.log)[-200:]}
                return self.send(200, json.dumps(state).encode())
            self.send(404, b"{}")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
            if self.path == "/touch":
                pv.touch(body); return self.send(200, b"{}")
            if self.path == "/control":
                c = json.loads(body or "{}")
                if "hour" in c: pv.hour = str(c["hour"])
                if "now" in c: pv.now = str(c["now"])
                if "service" in c: pv.service_on = bool(c["service"])
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
