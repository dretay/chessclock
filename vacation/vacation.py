"""Vacation countdown for the framebuffer: a photo of the ship at sea that follows the time of day
(day, dusk, night with cabin lights switching on and off), a rippling sea with foam and wake,
funnel smoke, fireworks at night, and a flip-clock of the days left at the top. Press and hold for
Settings (vacation_settings.py).

The drawing is all done by the C library vacfx (fx/vacfx.c), which owns the images and writes the
screen; this program decides what to show: the number, the time of day, when fireworks go off.
It deliberately doesn't import Pillow: on the 32 MB board every megabyte counts.

Settings: /etc/vacation.conf (KEY=VALUE lines, see vacation.conf). For trying it out:
  VACATION_CONF, VACATION_THEME_DIR, VACATION_LIB, VACATION_FB   other files than the installed ones
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
  VACATION_SHIPS=FILE       ship positions from this file (see vacation_map.py)
  VACATION_MAP_AFTER=5      show the fleet map first after this many seconds
  VACATION_NOW=2026-12-16T15:58   pretend the date and time are this (try the last day and sailing)
"""
import ctypes, datetime, json, math, os, random, signal, sys, time

import vacation_map
import vacation_settings
import vacation_touch as touch

FPS = 25
HOLD_SECS = 2.0       # press and hold this long for Settings
TAP_SECS = 0.3        # (the bar only appears after this, so a passing tap shows nothing)


def read_conf(path):
    conf = {}
    try:
        for line in open(path):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def smooth(a, b, v):
    t = min(1.0, max(0.0, (v - a) / (b - a))); return t * t * (3 - 2 * t)


def lighting(hour):
    """Sun height from the hour (noon 1, midnight -1) -> how much night and how much dusk (the mockup's)."""
    e = -math.cos(hour / 24 * 2 * math.pi)
    night = smooth(0.22, -0.2, e)
    dusk = math.exp(-((e - 0.02) / 0.2) ** 2)
    return night, dusk


FADE_SECS = 0.6                                     # countdown <-> map


def days_left(sail, today):
    return max(0, (sail - today).days)


class App:
    def __init__(self):
        here = os.path.dirname(os.path.abspath(__file__))
        self.conf_path = os.environ.get("VACATION_CONF", "/etc/vacation.conf")
        self.conf = read_conf(self.conf_path)
        theme = self.conf.get("THEME", "dream")
        self.theme_dir = os.environ.get("VACATION_THEME_DIR", os.path.join("/usr/share/vacation/themes", theme))
        self.ui_dir = os.environ.get("VACATION_UI_DIR", "/usr/share/vacation/ui")
        if not os.path.isdir(self.ui_dir): self.ui_dir = os.path.join(here, "ui")
        self.scene = json.load(open(os.path.join(self.theme_dir, "theme.json")))
        lib = os.environ.get("VACATION_LIB", "/usr/lib/libvacfx.so")
        if not os.path.exists(lib): lib = os.path.join(here, "fx", "libvacfx.so")
        self.fx = ctypes.CDLL(lib)
        self.fx.vfx_selftest.restype = ctypes.c_uint
        self.fx.vfx_stats.restype = ctypes.c_char_p
        self.fb_path = os.environ.get("VACATION_FB", "/dev/fb0")
        if self.fx.vfx_open(self.fb_path.encode(), self.theme_dir.encode()) != 0:
            sys.exit("vacation: couldn't start the display (see above)")
        s, c = self.scene, self.scene["cards"]
        self.fx.vfx_scene(s["horizon"], *s["stacks"][0], *s["stacks"][1], int(s["smoke_scale"] * 256), int(s["fireworks_scale"] * 256),
                          *s["bow"], *s["stern"], c["center_x"], c["top"], c["gap"], c["label_gap"])
        tube = [v for pt in s.get("tube", []) for v in pt]
        mast = s.get("mast", [-1, 0])
        self.fx.vfx_ambient(mast[0], mast[1], int(s.get("ambient_scale", 1.0) * 256), len(tube) // 2, (ctypes.c_int * max(1, len(tube)))(*tube))
        self.load_conf()
        self.fixed_hour = float(os.environ["VACATION_HOUR"]) if "VACATION_HOUR" in os.environ else None
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
        try: self.sail = datetime.date.fromisoformat(c.get("SAIL_DATE", "2027-02-16"))
        except ValueError:
            print("vacation: SAIL_DATE should look like 2027-02-16; got", c.get("SAIL_DATE")); self.sail = datetime.date.today()
        # when the ship sails that day: the last 24 hours count down in hours and minutes
        try: self.sail_time = datetime.time.fromisoformat(c.get("SAIL_TIME", "16:00") or "16:00")
        except ValueError: self.sail_time = datetime.time(16, 0)
        self.departure = datetime.datetime.combine(self.sail, self.sail_time)
        self.fx.vfx_lights_rate(int(c.get("LIGHTS_PER_MIN", "90")))
        self.fx.vfx_dither(int(c.get("DITHER", "1") or 1))
        self.fw_mode = c.get("FIREWORKS_MODE", "random")
        try: self.fw_every = float(c.get("FIREWORKS_EVERY_MIN", "15")) * 60     # at night, on average
        except ValueError: self.fw_every = 900
        try: h, m = (int(v) for v in c.get("FIREWORKS_SHOW_TIME", "21:00").split(":")); self.show_at = h + m / 60
        except ValueError: self.show_at = 21.0
        # the fleet map, in turn with the countdown
        self.map_on = c.get("MAP", "1") not in ("0", "")
        try: self.countdown_secs, self.map_secs = float(c.get("COUNTDOWN_SECS", "60")), float(c.get("MAP_SECS", "60"))
        except ValueError: self.countdown_secs, self.map_secs = 60.0, 60.0

    # time: real, or a preview's frame-by-frame clock
    def now(self): return self.clock if self.sim else time.monotonic()

    def tick(self):
        """One step of waiting (in a preview: one recorded frame)."""
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

    def hour(self, t):
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
            if t - last_check >= (0.2 if self.daylapse else 2.0):
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
                        if cards is not None and left > -3600: self.start_show(t)   # just now: a fireworks show
                        cards = ("sailed",)
                    # and fireworks now and then all through sailing day, day or night
                    if wall.date() == self.sail and t >= next_party:
                        next_party = t + random.uniform(120, 300); self.fx.vfx_fireworks(random.randint(4, 7))
                days = d
                # fireworks: random bursts at night, and/or the nightly show at its time
                if t >= next_fw:
                    next_fw = t + random.uniform(0.5, 1.5) * self.fw_every
                    if night > 0.6 and self.fw_mode in ("random", "both"): self.fx.vfx_fireworks(random.randint(3, 6))
                today = datetime.date.today()
                if self.fw_mode in ("show", "both") and shown_on != today and 0 <= (h - self.show_at) % 24 < 0.05:
                    shown_on = today; self.start_show(t)
                if not self.sim and t >= next_clock_save: next_clock_save = t + 300; save_clock()
            while self.show and self.show[0][0] <= t:
                _, n, g0, g1 = self.show.pop(0); self.fx.vfx_fireworks_gap(n, g0, g1)
            while demo and demo[0][0] <= t: self.fx.vfx_demo(demo.pop(0)[1])
            # press and hold for Settings: a bar fills under the cards
            if tp and total_frames % (1 if self.sim else 2) == 0:
                for ev, x, y in tp.poll(now):
                    if ev == "down": hold_start = now; print("vacation: press at (%d, %d)" % (x, y), flush=True)
                    elif ev == "up": hold_start = None; self.fx.vfx_hold(0)
            if hold_start is not None:
                k = (now - hold_start - TAP_SECS) / (HOLD_SECS - TAP_SECS)
                self.fx.vfx_hold(int(max(0.0, min(1.0, k)) * 256) or (1 if k > 0 else 0))
                if k >= 1:
                    hold_start = None; self.fx.vfx_hold(0)
                    settings = vacation_settings.Settings(self)
                    if settings.run():                                     # saved: pick up the new settings
                        self.conf = read_conf(self.conf_path); self.load_conf(); days = cards = None; last_check = -1e9
                    if settings.demo: self.start_show(self.now() - (0 if self.sim else start) + 0.5)   # the demo show
                    continue
            # the fleet map, every so often (not in the middle of a fireworks show, or a press)
            if self.map_on and t >= next_map and not self.show and hold_start is None:
                clock0 = 0 if self.sim else start
                def countdown_frame(): self.fx.vfx_frame(int((self.now() - clock0) * 1000) & 0x3fffffff)
                self.fade(0, countdown_frame)                      # the countdown fades out,
                vacation_map.MapScreen(self).run(self.map_secs)    # the map fades in and out by itself,
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
            spare = 1.0 / FPS - (time.monotonic() - now)
            if spare > 0: time.sleep(spare)
        self.fx.vfx_close()


CLOCK_FILE = "/var/lib/vacation/clock"


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
    try: saved = int(open(CLOCK_FILE).read().strip())
    except (OSError, ValueError): return
    if time.time() < saved:
        os.system("date -s @%d >/dev/null" % saved)
        print("vacation: clock restored to the last saved time,", time.ctime(), flush=True)


def main():
    if "VACATION_SIM_CLOCK" not in os.environ: restore_clock()
    App().run()


if __name__ == "__main__":
    main()
