"""Device settings, every app's: today's date and time, the display (day and night brightness, touch
calibration) and WiFi. Settings > Device › opens it in every app (a countdown app's Settings, the chess
clock's), through `device`, which stops the app first and starts it again after.

It's the Settings pages (vacation_settings.py) in their "device" kind, run by a small host of their own
here in place of a countdown app: the screen (the drawing library, over the blurred scene of the app that
was running, or the first countdown app's), the touch screen with the device's calibration, the device's
settings (/apps/data/device.conf), the backlight (a brightness chosen shows at once), and the clock.
On a desktop: PICKER_APPS (default /apps), PICKER_CURRENT, and VACATION_LIB, VACATION_FB, VACATION_TOUCH_*.
"""
import ctypes, os, signal, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import picker, sysapps
import vacation_settings
import vacation_touch as touch

CLOCK_FILE = os.path.join(picker.DATA, "system", "clock")     # (the saved time, shared by every app)


def minutes(text, default):
    try: h, m = (int(v) for v in text.split(":")); return h * 60 + m
    except (ValueError, AttributeError): return default


class Backlight:
    """The panel's backlight, on the chess clock's curve (level = max x p^2 / 10000)."""

    def __init__(self):
        self.path, self.max = None, 0
        base = "/sys/class/backlight"
        for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            try: self.max = int(open(os.path.join(base, d, "max_brightness")).read()); self.path = os.path.join(base, d, "brightness"); break
            except (OSError, ValueError): pass

    def set(self, percent):
        if not self.path: return
        try:
            with open(self.path, "w") as f: f.write(str(max(1, round(self.max * percent * percent / 10000))))
        except OSError: pass


class Host:
    """What the Settings pages ask of the app they're in."""

    def __init__(self, scene):
        self.fx = ctypes.CDLL(os.environ.get("VACATION_LIB", os.path.join(HERE, "fx", "libvacfx.so")))
        if self.fx.vfx_open(os.environ.get("VACATION_FB", "/dev/fb0").encode(), scene.encode()) != 0: sys.exit("device: no display")
        self.theme_dir, self.ui_dir = scene, os.environ.get("VACATION_UI_DIR", os.path.join(HERE, "ui"))
        self.device_path = self.conf_path = os.path.join(picker.DATA, "device.conf")
        self.conf = sysapps.read_conf(self.device_path)
        self.touch = touch.Touch.open(self.conf or picker.conf_of(picker.current()))
        self.module, self.sim, self.running, self.t0 = None, False, True, time.monotonic()
        c = self.conf
        try: self.day_bright = max(5, min(100, int(c.get("DAY_BRIGHTNESS", "100"))))
        except ValueError: self.day_bright = 100
        try: self.night_bright = max(5, min(100, int(c.get("NIGHT_BRIGHTNESS", "25"))))
        except ValueError: self.night_bright = 25
        self.night_start, self.night_end = minutes(c.get("NIGHT_START"), 21 * 60), minutes(c.get("NIGHT_END"), 7 * 60)
        self.bright_preview, self.backlight, self.shown = None, Backlight(), None
        signal.signal(signal.SIGTERM, lambda *a: setattr(self, "running", False))

    def now(self): return time.monotonic() - self.t0                  # (from the start: scripted presses' times)

    def tick(self):
        if self.bright_preview is not None and self.bright_preview != self.shown:   # (a brightness chosen: see it at once)
            self.backlight.set(self.bright_preview); self.shown = self.bright_preview
        time.sleep(0.02)

    def save_clock(self):
        try:
            os.makedirs(os.path.dirname(CLOCK_FILE), exist_ok=True)
            with open(CLOCK_FILE + ".tmp", "w") as f: f.write("%d\n" % time.time())
            os.replace(CLOCK_FILE + ".tmp", CLOCK_FILE)
        except OSError: pass


def main():
    found = picker.installed_apps()
    by_id = {a[0]: a for a in found}
    cur = picker.current()
    scene = picker.scene_of(by_id[cur][2]) if cur in by_id else None
    scene = scene or next((s for s in (picker.scene_of(a[2]) for a in found) if s), None)
    if not scene: sys.exit("device: no countdown app to draw with")
    host = Host(scene)
    vacation_settings.Settings(host, "device").run()
    host.fx.vfx_close()


if __name__ == "__main__":
    main()
