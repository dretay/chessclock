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
"""
import ctypes, datetime, json, math, os, random, signal, sys, time

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
        self.running = True
        signal.signal(signal.SIGTERM, lambda *a: setattr(self, "running", False))

    def load_conf(self):
        """The settings that can change while running (Settings saves them)."""
        c = self.conf
        try: self.sail = datetime.date.fromisoformat(c.get("SAIL_DATE", "2027-02-16"))
        except ValueError:
            print("vacation: SAIL_DATE should look like 2027-02-16; got", c.get("SAIL_DATE")); self.sail = datetime.date.today()
        self.fx.vfx_lights_rate(int(c.get("LIGHTS_PER_MIN", "90")))
        self.fx.vfx_dither(int(c.get("DITHER", "1") or 1))
        self.fw_mode = c.get("FIREWORKS_MODE", "random")
        try: self.fw_every = float(c.get("FIREWORKS_EVERY_MIN", "15")) * 60     # at night, on average
        except ValueError: self.fw_every = 900
        try: h, m = (int(v) for v in c.get("FIREWORKS_SHOW_TIME", "21:00").split(":")); self.show_at = h + m / 60
        except ValueError: self.show_at = 21.0

    # time: real, or a preview's frame-by-frame clock
    def now(self): return self.clock if self.sim else time.monotonic()

    def tick(self):
        """One step of waiting (in a preview: one recorded frame)."""
        if self.sim:
            if self.record: self.record.write(open(self.fb_path, "rb").read())
            self.clock += 1.0 / FPS
        else: time.sleep(0.02)

    def save_clock(self): save_clock()

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
        days = None; night = self.set_light(self.hour(0))
        next_fw = random.uniform(0.3, 1.0) * self.fw_every
        if os.environ.get("VACATION_FIREWORKS"): next_fw = 1.0
        self.show = []; shown_on = None
        if os.environ.get("VACATION_SHOW"): self.start_show(0.5)
        stop_after = int(os.environ.get("VACATION_FRAMES", "0"))
        next_clock_save = 0.0
        while self.running:
            now = self.now(); t = now - (0 if self.sim else start)
            t_ms = int(t * 1000) & 0x3fffffff           # wraps every 12 days; the drawing copes with one odd frame
            if t - last_check >= (0.2 if self.daylapse else 2.0):
                last_check = t
                h = self.hour(t); night = self.set_light(h)
                d = days_left(self.sail, datetime.date.today())
                if d != days: self.fx.vfx_days(d, 1, t_ms + 600); days = d       # flips over (also at start)
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
                        self.conf = read_conf(self.conf_path); self.load_conf(); days = None; last_check = -1e9
                    if settings.demo: self.start_show(self.now() - (0 if self.sim else start) + 0.5)   # the demo show
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
