"""The countdown for the framebuffer (the runtime the countdown apps run on): a picture that follows the time of day
(day, dusk, night with cabin lights switching on and off), a rippling sea with foam and wake,
funnel smoke, fireworks at night, and a flip-clock of the days left at the top. Press and hold for
Settings (vacation_settings.py).

The drawing is all done by the C library vacfx (fx/vacfx.c), which owns the images and writes the
screen; this program decides what to show: the number, the time of day, when fireworks go off.
It deliberately doesn't import Pillow: on the 32 MB board every megabyte counts.

The countdown runtime (/apps/countdown on the board): every countdown app (the cruise, the castle:
see apps.py) starts it from its own folder with its `run` (`exec /apps/countdown/launch`); the app
brings the scene, screens and settings. Its settings and saved state are in APP_DATA
(/apps/data/<app>): countdown.conf (KEY=VALUE lines; made the first time, see apps.settings_file).
For trying it out:
  VACATION_APP=apps/castle  the app to run (default: the current folder)
  VACATION_CONF, VACATION_THEME_DIR, VACATION_LIB, VACATION_FB   other files than the usual ones
  VACATION_HOUR=21.5        pretend it's always this time of day
  VACATION_DAYLAPSE=90      run a whole day in this many seconds
  VACATION_FRAMES=N         stop after N frames
  VACATION_FIREWORKS=1      fireworks right away (if it's night)
  VACATION_LOG_SECS=10      log the frame rate this often (default every minute)
  VACATION_SIM_CLOCK=0      a preview: time steps exactly one frame per frame, from this many seconds
  VACATION_RECORD=FILE      (preview) append every frame to FILE, raw 800x480 BGRX
  VACATION_SIM_END=20       (preview) stop at this time
  VACATION_DEMO=gulls@2,... (preview) set off gulls, dolphins or the raft at these times
  VACATION_TOUCH_SCRIPT=F   (preview) presses from a file instead of the touch chip (see vacation_touch.py)
  VACATION_SHOW=1           start the nightly fireworks show right away
  VACATION_UI_DIR           the Settings images (ui.bin.gz), if not the installed ones
  VACATION_MAP_DIR          the fleet map's chart (map.rgb.gz, map.json), if not the installed one
  VACATION_SCHEDULE=FILE    the ships' schedules from this file, not the app's schedule.json (see apps/countdown/ships/screen.py)
  VACATION_MAP_AFTER=5      show the module's first screen (the fleet map) after this many seconds
  VACATION_NOW=2026-12-16T15:58   pretend the date and time are this (try the last day and sailing)
"""
import ctypes, datetime, json, math, os, random, signal, sys, time

import apps
import vacation_touch as touch

FPS = 25
HOLD_SECS = 2.0       # press and hold this long for Settings
TAP_SECS = 0.3        # (the bar only appears after this, so a passing tap shows nothing)
SWITCH_SECS = 0.8     # a press let go sooner than this is a tap: the next screen (the app's own, or the countdown)


read_conf = apps.read_conf


def smooth(a, b, v):
    t = min(1.0, max(0.0, (v - a) / (b - a))); return t * t * (3 - 2 * t)


def lighting(hour):
    """Sun height from the hour (noon 1, midnight -1) -> how much night and how much dusk (the mockup's)."""
    e = -math.cos(hour / 24 * 2 * math.pi)
    night = smooth(0.22, -0.2, e)
    dusk = math.exp(-((e - 0.02) / 0.2) ** 2)
    return night, dusk


# the drawing library's scene effects (vfx_effects): theme.json lists the ones its scene has
REMOTE_LIVE = "/tmp/countdown-live.json"           # (the board: the Mac's Controls, in RAM: gone at a reboot)
EFFECTS = {"water": 1, "wake": 2, "smoke": 4, "gulls": 8, "birds": 8, "dolphins": 16, "raft": 32, "twinkle": 64, "foam": 128, "fireflies": 256, "mist": 512}   # ("birds": the gulls, any scene's)

FADE_SECS = 0.6                                     # countdown <-> a module's screen


# the app's settings and saved state (S99app sets it to /apps/data/<app> on the board)
DATA = os.environ.get("APP_DATA")

class Backlight:
    """The panel's backlight (Linux's backlight interface: PWM on the board), as a percentage on the same
    curve as Device settings' (level = max x p^2 / 10000: even steps look even). Nothing on a desktop."""

    def __init__(self):
        self.path, self.max, self.level = None, 0, None
        base = "/sys/class/backlight"
        for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            try: self.max = int(open(os.path.join(base, d, "max_brightness")).read()); self.path = os.path.join(base, d, "brightness"); break
            except (OSError, ValueError): pass

    def set(self, percent):
        if not self.path: return
        level = max(1, round(self.max * percent * percent / 10000))
        if level == self.level: return
        try:
            with open(self.path, "w") as f: f.write(str(level))
            self.level = level
        except OSError: pass


def minutes(text, default):
    try: h, m = (int(v) for v in text.split(":")); return h * 60 + m
    except (ValueError, AttributeError): return default


def days_left(sail, today):
    return max(0, (sail - today).days)


class App:
    def __init__(self):
        app_dir = os.environ.get("VACATION_APP") or os.getcwd()
        app_id = json.load(open(apps.manifest_path(app_dir) or os.path.join(app_dir, "app.json")))["id"]
        self.module = apps.App(app_dir, DATA or os.path.join("/apps/data", app_id))   # the trip: scene, screens, data
        self.conf_path = os.environ.get("VACATION_CONF") or apps.settings_file(self.module)
        # the device's settings (touch calibration, brightness, CPU): shared by every app
        self.device_path = None if os.environ.get("VACATION_CONF") else apps.ensure_device(self.module, self.conf_path)
        self.conf = apps.read_settings(self.conf_path, self.device_path)
        mhz = self.conf.get("CPU_MHZ", "").strip()                      # (the CPU clock: CPU_MHZ=600, say)
        if mhz.isdigit() and not os.environ.get("VACATION_SIM_CLOCK") and os.path.exists("/usr/sbin/setcpu"): os.system("setcpu %s" % mhz)
        self.theme_dir = os.environ.get("VACATION_THEME_DIR") or self.module.scene_dir(self.conf)
        self.screens = self.module.screens()
        self.ui_dir = os.environ.get("VACATION_UI_DIR", os.path.join(apps.SYSTEM, "ui"))     # (the system package's)
        self.scene = json.load(open(os.path.join(self.theme_dir, "theme.json")))
        self.fireworks_on = self.scene.get("fireworks", True) is not False   # (a scene can have none: a trail, a city)
        lib = os.environ.get("VACATION_LIB", os.path.join(apps.SYSTEM, "fx", "libvacfx.so"))
        self.fx = ctypes.CDLL(lib)
        self.fx.vfx_selftest.restype = ctypes.c_uint
        self.fx.vfx_stats.restype = ctypes.c_char_p
        self.fb_path = os.environ.get("VACATION_FB", "/dev/fb0")
        stop_splash()
        if self.fx.vfx_open(self.fb_path.encode(), self.theme_dir.encode()) != 0:
            sys.exit("vacation: couldn't start the display (see above)")
        s, c = self.scene, self.scene["cards"]
        # the scene's own effects (theme.json "effects"; all of them when it doesn't say: the ship's)
        if "effects" in s:
            self.fx.vfx_effects(sum(EFFECTS.get(e, 0) for e in s["effects"]))
        ff = s.get("fireflies") or {}                    # (fireflies: zones x, y, r; how many)
        if ff.get("points"):
            xyr = [int(v) for p in ff["points"][:16] for v in (p[0], p[1], p[2] if len(p) > 2 else 30)]
            self.fx.vfx_fireflies(len(xyr) // 3, (ctypes.c_int * len(xyr))(*xyr), int(float(ff.get("amount", 1.0)) * 256))
        mi = s.get("mist") or {}                         # (mist: a box, how much, when)
        if len(mi.get("box") or []) == 4:
            self.fx.vfx_mist(*[int(v) for v in mi["box"]], int(float(mi.get("amount", 1.0)) * 256), 1 if mi.get("when") == "always" else 0)
        fo = s.get("foam") or {}                         # (a scene's own foam: points and sizes, how much, which way)
        if fo.get("points"):
            xyr = [int(v) for p in fo["points"][:16] for v in (p[0], p[1], p[2] if len(p) > 2 else 12)]
            self.fx.vfx_foam(len(xyr) // 3, (ctypes.c_int * len(xyr))(*xyr), int(float(fo.get("amount", 1.0)) * 256),
                             {"still": 0, "left": 1, "right": 2, "falling": 3, "toward": 4}.get(fo.get("flow", "still"), 0))
        water = s.get("water") or {}                     # (a scene's own water, water.raw.gz: how strong, how fast)
        self.fx.vfx_water(int(float(water.get("strength", 1.0)) * 256), int(float(water.get("speed", 1.0)) * 256))
        show = s.get("show") or {}                       # (the lights' show: theme.json "show", else every pattern)
        prog = [int(v) for v in show.get("program", [])]
        self.fx.vfx_twinkle_program((ctypes.c_int * max(1, len(prog)))(*prog), len(prog), int(float(show.get("secs", 12)) * 1000))
        # (the ship's own places: its funnels' tops for the smoke, its bow and stern for the wake; a scene
        # without those effects leaves them out)
        stacks = s.get("stacks", [[-50, -50], [-50, -50]])
        self.fx.vfx_scene(s["horizon"], *stacks[0], *stacks[1], int(s.get("smoke_scale", 0.8) * 256), int(s.get("fireworks_scale", 0.85) * 256),
                          *s.get("bow", [799, 479]), *s.get("stern", [0, 479]), c["center_x"], c["top"], c["gap"], c["label_gap"])
        self.fx.vfx_cards_scale(int(float(c.get("scale", 1.0)) * 256))         # (the countdown's size: theme.json cards.scale)
        if c.get("scale3"): self.fx.vfx_cards_scale3(int(c["scale3"] * 256))     # (three digits: smaller cards, of those)
        tube = [v for pt in s.get("tube", []) for v in pt]
        mast = s.get("mast", [-1, 0])
        self.fx.vfx_ambient(mast[0], mast[1], int(s.get("ambient_scale", 1.0) * 256), len(tube) // 2, (ctypes.c_int * max(1, len(tube)))(*tube))
        sm = s.get("smoke") or {}                        # (a scene's own smoke: where from, how big, the wind; after vfx_scene: it sets the ship's funnels)
        if sm.get("points"):
            xy = [int(v) for p in sm["points"][:8] for v in p]
            rate = int(sm.get("rate", 4)); dense = float(sm.get("density", 1.2 + rate * 0.2))   # (thicker smoke: more puffs, denser)
            self.fx.vfx_smoke(len(xy) // 2, (ctypes.c_int * len(xy))(*xy), int(float(sm.get("scale", 0.8)) * 256),
                              int(float(sm.get("wind", 0)) * 256), rate, int(dense * 256))
        self.backlight = Backlight()
        self.bl_shown, self.bl_at, self.bright_preview = None, 0.0, None
        self.screen_press, self.want_settings, self.screen_tapped = None, False, False
        self.load_conf()
        self.fixed_hour = float(os.environ["VACATION_HOUR"]) if "VACATION_HOUR" in os.environ else None
        # in the previewer: its live controls (the time-of-day slider, fireworks), without a restart
        # on the board: the Mac's Controls set to Device (over the USB console: tools/preview/remote.py), into RAM
        self.live_path = os.path.join(os.environ["PREVIEW_DIR"], "live.json") if os.environ.get("PREVIEW_DIR") \
            else os.environ.get("VACATION_LIVE") or (REMOTE_LIVE if os.path.exists("/apps/current") else None)
        self.live_every = 0.0 if os.environ.get("PREVIEW_DIR") else 0.3       # (looked at a few times a second on the board)
        self.live_looked = -1e9
        self.live_at, self.live = 0.0, {}
        self.go_screen = False
        self.daylapse = float(os.environ.get("VACATION_DAYLAPSE", "0"))
        self.log_every = float(os.environ.get("VACATION_LOG_SECS", "60"))
        # a preview steps time exactly one frame per frame, and can record every frame
        self.sim = "VACATION_SIM_CLOCK" in os.environ
        self.clock = float(os.environ.get("VACATION_SIM_CLOCK", "0"))
        self.record = open(os.environ["VACATION_RECORD"], "ab") if os.environ.get("VACATION_RECORD") else None
        self.touch = touch.Touch.open(self.conf)
        self.night = 0.0
        self.fade_lvl = 256
        self.wall_base = datetime.datetime.fromisoformat(os.environ["VACATION_NOW"]) if os.environ.get("VACATION_NOW") else None
        self.sim_start_wall = datetime.datetime.now(); self.mono_start = time.monotonic()
        self.running = True
        signal.signal(signal.SIGTERM, lambda *a: setattr(self, "running", False))

    def load_conf(self):
        """The settings that can change while running (Settings saves them)."""
        c = self.conf
        # the trip's day (TRIP_DATE; SAIL_DATE in settings from before modules) and the time it counts down to
        # on its last day (TRIP_TIME, else the module's own: the ship sails at 4 PM, the park opens at 9)
        trip = c.get("TRIP_DATE") or c.get("SAIL_DATE") or "2027-02-16"
        try: self.sail = datetime.date.fromisoformat(trip)
        except ValueError:
            print("vacation: TRIP_DATE should look like 2027-02-16; got", trip); self.sail = datetime.date.today()
        # when the ship sails that day: the last 24 hours count down in hours and minutes
        at = c.get("TRIP_TIME") or c.get("SAIL_TIME") or self.module.meta.get("countdown", {}).get("time", "16:00")
        try: self.sail_time = datetime.time.fromisoformat(at)
        except ValueError: self.sail_time = datetime.time(16, 0)
        self.departure = datetime.datetime.combine(self.sail, self.sail_time)
        self.fx.vfx_lights_rate(int(c.get("LIGHTS_PER_MIN", "90")))
        self.fx.vfx_dither(int(c.get("DITHER", "1") or 1))
        self.fw_mode = c.get("FIREWORKS_MODE", "random")
        try: self.fw_every = float(c.get("FIREWORKS_EVERY_MIN", "15")) * 60     # at night, on average
        except ValueError: self.fw_every = 900
        try: h, m = (int(v) for v in c.get("FIREWORKS_SHOW_TIME", "21:00").split(":")); self.show_at = h + m / 60
        except ValueError: self.show_at = 21.0
        # the backlight: day and night brightness (percent) and when night is (the device's settings)
        try: self.day_bright = max(5, min(100, int(c.get("DAY_BRIGHTNESS", "100"))))
        except ValueError: self.day_bright = 100
        try: self.night_bright = max(5, min(100, int(c.get("NIGHT_BRIGHTNESS", "25"))))
        except ValueError: self.night_bright = 25
        self.night_start = minutes(c.get("NIGHT_START"), 21 * 60)
        self.night_end = minutes(c.get("NIGHT_END"), 7 * 60)
        # the module's screens (the cruise's fleet map), in turn with the countdown: each for its
        # seconds setting, while its on/off setting isn't 0
        try: self.countdown_secs = float(c.get("COUNTDOWN_SECS", "60"))
        except ValueError: self.countdown_secs = 60.0
        self.playlist = []
        for spec, cls in self.screens:
            if spec.get("enabled") and c.get(spec["enabled"], "1") in ("0", ""): continue
            v = spec.get("secs", 60)                     # (seconds, or the name of a setting holding them)
            try: secs = float(v) if isinstance(v, (int, float)) else float(c.get(v, "60"))
            except ValueError: secs = 60.0
            self.playlist.append((cls, secs, spec))
        self.next_screen = 0

    # time: real, or a preview's frame-by-frame clock
    def now(self): return self.clock if self.sim else time.monotonic()

    def screen_touch(self, now):
        """For an app's screen (the wait-times board, the fleet map): "tap" when a press is let go (the next
        screen, or back to the countdown), "hold" once one has lasted HOLD_SECS (Settings, as on the
        countdown), else None."""
        tp = self.touch
        for ev, x, y in (tp.poll(now) if tp else []):
            if ev == "down": self.screen_press = now
            elif ev == "up":
                was, self.screen_press = self.screen_press, None
                if was is not None: self.screen_tapped = True; return "tap"
        if self.screen_press is not None and now - self.screen_press >= HOLD_SECS:
            self.screen_press = None; self.want_settings = True; return "hold"
        return None

    def is_night(self, t):
        m = self.hour(t) * 60; a, b = self.night_start, self.night_end
        return (a <= m < b) if a <= b else (m >= a or m < b)

    def update_backlight(self):
        """Ease the backlight toward the day or night brightness (over about a minute; at once the first
        time); Settings > Display previews a level by setting bright_preview."""
        now = time.monotonic()
        if now - self.bl_at < 0.25: return
        dt, self.bl_at = now - self.bl_at, now
        target = self.bright_preview if self.bright_preview is not None else \
            self.night_bright if self.is_night(self.now()) else self.day_bright
        if self.bl_shown is None or self.bright_preview is not None: self.bl_shown = float(target)
        else:
            step = 100 / 60 * min(dt, 1.0)
            self.bl_shown += max(-step, min(step, target - self.bl_shown))
        self.backlight.set(round(self.bl_shown))

    def tick(self):
        """One step of waiting (in a preview: one recorded frame)."""
        self.update_backlight()
        if self.sim:
            if self.record: self.record.write(open(self.fb_path, "rb").read())
            self.clock += 1.0 / FPS
        else: time.sleep(0.02)

    def save_clock(self): save_clock()

    def wall(self):
        """The date and time now (a preview's own, from VACATION_NOW and its frame clock)."""
        if self.sim or self.wall_base:
            base = self.wall_base or self.sim_start_wall
            return base + datetime.timedelta(seconds=self.clock if self.sim else time.monotonic() - self.mono_start)
        return datetime.datetime.now()

    def fade(self, to, frame=None, secs=FADE_SECS):
        """Fade the screen to brightness `to` (0 black .. 256 normal), calling frame() each step to
        keep whatever's showing moving."""
        frm = self.fade_lvl; t0 = self.now()
        while self.running:
            k = min(1.0, (self.now() - t0) / secs)
            if frame: frame()
            self.fx.vfx_fade(int(frm + (to - frm) * k)); self.tick()
            if k >= 1: break
        self.fade_lvl = to

    def live_controls(self, t):
        """The previewer's live.json (or, on the board, REMOTE_LIVE), when it's changed: {"hour": h or null,
        "fireworks": n, "show": n, "birds": n, ...} (counters: each larger value fires once). True if the hour changed."""
        if t - self.live_looked < self.live_every and t >= self.live_looked: return False
        self.live_looked = t
        try: at = os.path.getmtime(self.live_path)
        except (OSError, TypeError): return False
        if at == self.live_at: return False
        self.live_at = at
        try: new = json.load(open(self.live_path))
        except (OSError, ValueError): return False
        old, self.live = self.live, new
        def fired(k): return old and new.get(k, 0) > old.get(k, 0)
        if fired("fireworks"): self.fx.vfx_fireworks(random.randint(4, 7))
        if fired("show"): self.start_show(t)
        if fired("birds"): self.fx.vfx_demo(1)                                              # (birds across, now)
        if fired("fireflies"): self.fx.vfx_demo(4)                                          # (fireflies out, now)
        if bool(new.get("windows_hold")) != bool(old.get("windows_hold")):                 # (painting windows: all lit, still)
            self.fx.vfx_windows_hold(1 if new.get("windows_hold") else 0)
        if new.get("pattern", -1) != old.get("pattern", -1): self.fx.vfx_twinkle_pin(int(new.get("pattern", -1)))
        go = new.get("screen_go", 0)                     # (show a screen now: app.json's nth; just asked, if the app has only now started)
        if go and ((old and go > old.get("screen_go", 0)) or (not old and time.time() - float(new.get("screen_at", 0)) < 20)):
            want = int(new.get("screen", 0))
            hit = [i for i, (_, _, spec) in enumerate(self.playlist) if spec.get("_at") == want]
            if hit: self.next_screen = hit[0]; self.go_screen = True
            else: print("countdown: screen %d isn't showing (turned off in the settings, or it didn't load)" % (want + 1), flush=True)
        return new.get("hour") != old.get("hour") or not old

    def hour(self, t):
        if self.live.get("hour") is not None: return float(self.live["hour"]) % 24
        if self.fixed_hour is not None:
            return (self.fixed_hour + (t / self.daylapse * 24 if self.daylapse else 0)) % 24
        lt = time.localtime(); return lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600

    def set_light(self, h):
        night, dusk = lighting(h)
        wn = night; wu = dusk * (1 - night); wd = max(0.0, 1 - wn - wu)
        q = [int(round(v * 256)) for v in (wd, wu, wn)]; q[0] += 256 - sum(q)
        self.fx.vfx_light(q[0], q[1], q[2], int(smooth(0.35, 0.75, night) * 256), int(night * 256), int(dusk * 256))
        return night

    def start_show(self, t):
        """The nightly show: two minutes of rockets in volleys, then a quick finale."""
        self.show = []; at = t
        while at < t + 100: self.show.append((at, random.randint(3, 5), 300, 550)); at += random.uniform(3.5, 6.0)
        self.show.append((t + 102, 30, 90, 170))
        print("vacation: fireworks show", flush=True)

    def run(self):
        sim_end = float(os.environ.get("VACATION_SIM_END", "1e9"))
        demo = []                                       # e.g. VACATION_DEMO=gulls@2,dolphins@5,raft@8
        for item in filter(None, os.environ.get("VACATION_DEMO", "").split(",")):
            what, at = item.split("@"); demo.append((float(at), {"gulls": 1, "dolphins": 2, "raft": 3}[what]))
        tp, hold_start = self.touch, None
        start = self.now(); frames = 0; total_frames = 0; busy = 0; last_check = -1e9; last_log = start
        reference = self.fx.vfx_selftest(); errors = 0
        days = None; cards = None; next_party = 0.0; night = self.set_light(self.hour(0))
        next_fw = random.uniform(0.3, 1.0) * self.fw_every
        if os.environ.get("VACATION_FIREWORKS"): next_fw = 1.0
        self.show = []; shown_on = None
        if os.environ.get("VACATION_SHOW"): self.start_show(0.5)
        stop_after = int(os.environ.get("VACATION_FRAMES", "0"))
        next_clock_save = 0.0
        next_map = float(os.environ.get("VACATION_MAP_AFTER", self.countdown_secs))
        while self.running:
            now = self.now(); t = now - (0 if self.sim else start)
            t_ms = int(t * 1000) & 0x3fffffff           # wraps every 12 days; the drawing copes with one odd frame
            moved = self.live_path is not None and self.live_controls(t)
            if moved or t - last_check >= (0.2 if self.daylapse else 2.0):
                last_check = t
                h = self.hour(t); night = self.night = self.set_light(h)
                wall = self.wall(); left = (self.departure - wall).total_seconds()
                d = days_left(self.sail, wall.date())
                if left > 24 * 3600:                                           # days
                    if ("days", d) != cards: self.fx.vfx_days(d, 1, t_ms + 600); cards = ("days", d)
                elif left > 0:                                                 # the last day: HH:MM to sailing
                    mins = int(math.ceil(left / 60)); hm = divmod(mins, 60)
                    if ("clock", hm) != cards: self.fx.vfx_clock(hm[0], hm[1], 1, t_ms + 600); cards = ("clock", hm)
                else:                                                          # sailed: "Bon voyage!"
                    if cards != ("sailed",):
                        self.fx.vfx_banner(1)
                        if cards is not None and left > -3600 and self.fireworks_on: self.start_show(t)   # just now: a fireworks show
                        cards = ("sailed",)
                    # and fireworks now and then all through sailing day, day or night
                    if wall.date() == self.sail and t >= next_party and self.fireworks_on:
                        next_party = t + random.uniform(120, 300); self.fx.vfx_fireworks(random.randint(4, 7))
                days = d
                # fireworks: random bursts at night, and/or the nightly show at its time
                if t >= next_fw:
                    next_fw = t + random.uniform(0.5, 1.5) * self.fw_every
                    if night > 0.6 and self.fw_mode in ("random", "both") and self.fireworks_on: self.fx.vfx_fireworks(random.randint(3, 6))
                today = datetime.date.today()
                if self.fireworks_on and self.fw_mode in ("show", "both") and shown_on != today and 0 <= (h - self.show_at) % 24 < 0.05:
                    shown_on = today; self.start_show(t)
                if not self.sim and t >= next_clock_save: next_clock_save = t + 300; save_clock()
            while self.show and self.show[0][0] <= t:
                _, n, g0, g1 = self.show.pop(0); self.fx.vfx_fireworks_gap(n, g0, g1)
            while demo and demo[0][0] <= t: self.fx.vfx_demo(demo.pop(0)[1])
            # press and hold for Settings: a bar fills under the cards
            if tp and total_frames % (1 if self.sim else 2) == 0:
                for ev, x, y in tp.poll(now):
                    if ev == "down": hold_start = now; print("vacation: press at (%d, %d)" % (x, y), flush=True)
                    elif ev == "up":
                        if hold_start is not None and now - hold_start < SWITCH_SECS and self.playlist:
                            next_map = -1                              # a tap: the app's screen, now
                        hold_start = None; self.fx.vfx_hold(0)
            if hold_start is not None:
                k = (now - hold_start - TAP_SECS) / (HOLD_SECS - TAP_SECS)
                self.fx.vfx_hold(int(max(0.0, min(1.0, k)) * 256) or (1 if k > 0 else 0))
                if k >= 1:
                    hold_start = None; self.fx.vfx_hold(0)
                    self.want_settings = True
            if self.want_settings:                                     # (held on the countdown, or on a screen)
                self.want_settings = False
                import vacation_settings                          # (only now: it's a second of loading, and memory)
                settings = vacation_settings.Settings(self)
                if settings.run():                                         # saved: pick up the new settings
                    self.conf = apps.read_settings(self.conf_path, self.device_path); self.load_conf(); days = cards = None; last_check = -1e9
                if settings.demo: self.start_show(self.now() - (0 if self.sim else start) + 0.5)   # the demo show
                # (the countdown's time on screen starts again: time in Settings doesn't count, or a screen
                # would come straight away)
                next_map = max(next_map, self.now() - (0 if self.sim else start) + self.countdown_secs)
                continue
            # the module's next screen, every so often (not in the middle of a fireworks show, or a press)
            # (a tap shows it even during a fireworks show; on its own timer, it waits for the show to end)
            if self.go_screen: self.go_screen = False; next_map = -1      # (the previewer's "show it now")
            # (the previewer's "Stay on the scene": no screens by themselves, a tap still brings one)
            if self.playlist and t >= next_map and (not self.show or next_map < 0) and hold_start is None and (next_map < 0 or not self.live.get("stay")):
                clock0 = 0 if self.sim else start
                def countdown_frame(): self.fx.vfx_frame(int((self.now() - clock0) * 1000) & 0x3fffffff)
                self.fade(0, countdown_frame)                      # the countdown fades out,
                for _ in self.playlist:                            # the screens: each fades in and out by itself;
                    cls, secs, spec = self.playlist[self.next_screen % len(self.playlist)]; self.next_screen += 1
                    self.screen_tapped = False
                    screen = cls(self); screen.spec = spec        # (its settings from app.json: a weather screen's place)
                    screen.run(secs)                               # a tap on one goes to the next, and from the
                    if not self.screen_tapped or self.want_settings: break    # last back to the countdown
                self.fade(256, countdown_frame)                    # and the countdown comes back
                next_map = self.now() - (0 if self.sim else start) + self.countdown_secs
                frames = busy = 0; last_log = self.now()           # (the frame-rate log is about the countdown only)
                continue
            busy += self.fx.vfx_frame(t_ms); frames += 1; total_frames += 1
            if stop_after and total_frames >= stop_after: break
            if self.sim:
                self.tick()
                if self.clock >= sim_end: break
                continue
            if now - last_log >= self.log_every:
                ok = self.fx.vfx_selftest() == reference; errors += not ok
                print("vacation: %.1f fps, drawing %.0f%% of the time, %d days, %s" % (
                    frames / (now - last_log), busy / 1e6 / (now - last_log) * 100, days or 0,
                    "self-check ok" if ok else "SELF-CHECK FAILED (%d so far): the CPU is making mistakes" % errors), flush=True)
                if os.environ.get("VACATION_STATS"): print("   ", self.fx.vfx_stats().decode(), flush=True)
                frames = 0; busy = 0; last_log = now
            self.update_backlight()
            spare = 1.0 / FPS - (time.monotonic() - now)
            if spare > 0: time.sleep(spare)
        self.fx.vfx_close()


# (shared by every app, so switching between them keeps the time; where it was before)
CLOCK_FILE = os.path.join(os.path.dirname(DATA) if DATA else "/apps/data", "system", "clock")
OLD_CLOCK_FILES = [os.path.join(os.path.dirname(CLOCK_FILE), "..", "countdown", "clock"), os.path.join(apps.OLD_DATA, "clock")]


def stop_splash():
    """Stop the loading animation (splashanim: the boot splash's dots, or the app picker's) and wait for
    it to finish, so its last frame can't land on this app's first."""
    try: pid = int(open("/var/run/splashanim.pid").read())
    except (OSError, ValueError): return
    try: os.kill(pid, signal.SIGTERM)
    except OSError: return
    for _ in range(50):
        try: os.kill(pid, 0)
        except OSError: return
        time.sleep(0.01)


def save_clock():
    """The board has no clock battery: keep the time on the SD card every few minutes, so after a power
    cut the clock is only behind by how long it was off (instead of back in 1970)."""
    try:
        os.makedirs(os.path.dirname(CLOCK_FILE), exist_ok=True)
        with open(CLOCK_FILE + ".tmp", "w") as f: f.write("%d\n" % time.time())
        os.replace(CLOCK_FILE + ".tmp", CLOCK_FILE)
    except OSError:
        pass


def restore_clock():
    saved = 0
    for f in [CLOCK_FILE] + OLD_CLOCK_FILES:
        try: saved = max(saved, int(open(f).read().strip()))
        except (OSError, ValueError): pass
    if not saved: return
    if time.time() < saved:
        os.system("date -s @%d >/dev/null" % saved)
        print("vacation: clock restored to the last saved time,", time.ctime(), flush=True)


def main():
    if "VACATION_SIM_CLOCK" not in os.environ: restore_clock()
    App().run()


if __name__ == "__main__":
    main()
