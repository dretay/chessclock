"""Touch input for the countdown, its Settings screen and the app picker.

Touch: the board's NS2009 resistive touch chip, polled over I2C (the same chip and the same
tested reading sequence as the project's earlier apps). Calibration comes from the
TOUCH_* keys in vacation.conf.

ScriptTouch: for previews on a desktop. Reads presses from a file, one per line:
    START_SECONDS X Y HOLD_SECONDS
(# starts a comment). Times are on the shared preview clock (VACATION_SIM_CLOCK), so a script can
open Settings, tap through it and come back to the countdown.

poll() returns a list of events: ("down", x, y), ("move", x, y), ("up", x, y).
"""
import fcntl, os, time


class Touch:
    I2C_SLAVE = 0x0703                 # ioctl: set the address for read/write
    ADDRESS = 0x48
    CMD_X, CMD_Y, CMD_Z1, CMD_Z2 = 0xC0, 0xD0, 0xE0, 0xF0
    PRESS_Z1 = 150                     # pressure: idle reads <60, a press 300+
    MIN_SAMPLES = 3                    # a press counts after 3 steady readings
    MAX_SPREAD = 300                   # (raw units, ~60px): noise jumps around
    RELEASE_SECS = 0.12                # no pressure for this long = released

    def __init__(self, bus, conf, width=800, height=480):
        self.fd = os.open(bus, os.O_RDWR)
        fcntl.ioctl(self.fd, self.I2C_SLAVE, self.ADDRESS)
        self._measure(self.CMD_Z1)     # raises OSError if the chip doesn't answer
        self.width, self.height = width, height
        self.samples, self.down, self.quiet, self.last_pressed, self.pos = [], False, 0, 0.0, (0, 0)
        self.raw = (0, 0)                  # the raw reading behind the last press (for calibrating)
        def num(k, d):
            try: return int(conf.get(k, d))
            except ValueError: return d
        self.cfg = {k: num(k, d) for k, d in (("TOUCH_X_MIN", 0), ("TOUCH_X_MAX", 4095), ("TOUCH_Y_MIN", 0),
                                               ("TOUCH_Y_MAX", 4095), ("TOUCH_SWAP_XY", 0))}

    @classmethod
    def open(cls, conf):
        if os.environ.get("VACATION_TOUCH_SCRIPT"):
            return ScriptTouch(os.environ["VACATION_TOUCH_SCRIPT"])
        if os.environ.get("VACATION_TOUCH_PIPE"):
            return PipeTouch(os.environ["VACATION_TOUCH_PIPE"])
        bus = os.environ.get("VACATION_TOUCH_BUS", "/dev/i2c-0")
        try:
            return cls(bus, conf)
        except OSError as e:
            print("vacation: no touch chip on %s: %s" % (bus, e), flush=True)
            return None

    def _measure(self, cmd):
        os.write(self.fd, bytes([cmd]))
        hi, lo = os.read(self.fd, 2)
        return (hi << 4) | (lo >> 4)   # 12-bit result

    def to_screen(self, rx, ry):
        c = self.cfg
        if c["TOUCH_SWAP_XY"]: rx, ry = ry, rx
        x = (rx - c["TOUCH_X_MIN"]) * self.width / ((c["TOUCH_X_MAX"] - c["TOUCH_X_MIN"]) or 1)
        y = (ry - c["TOUCH_Y_MIN"]) * self.height / ((c["TOUCH_Y_MAX"] - c["TOUCH_Y_MIN"]) or 1)
        return min(self.width - 1, max(0, int(x))), min(self.height - 1, max(0, int(y)))

    def poll(self, now=None):
        try:
            # X, Y, Z1, Z2 in this order (reading pressure alone straight after idle misses presses)
            x, y = self._measure(self.CMD_X), self._measure(self.CMD_Y)
            pressed = self._measure(self.CMD_Z1) >= self.PRESS_Z1
            self._measure(self.CMD_Z2)
        except OSError:
            return []
        now = time.monotonic()
        if pressed:
            self.quiet, self.last_pressed = 0, now
            self.samples = (self.samples + [(x, y)])[-8:]
            if len(self.samples) < self.MIN_SAMPLES: return []
            recent = self.samples[-self.MIN_SAMPLES:]
            xs, ys = sorted(p[0] for p in recent), sorted(p[1] for p in recent)
            if not self.down:
                if max(xs[-1] - xs[0], ys[-1] - ys[0]) <= self.MAX_SPREAD:
                    self.down = True; self.raw = (xs[1], ys[1]); self.pos = self.to_screen(xs[1], ys[1])
                    return [("down",) + self.pos]
                return []
            sx, sy = self.to_screen(xs[1], ys[1])
            if abs(sx - self.pos[0]) + abs(sy - self.pos[1]) >= 4:      # ignore jitter
                self.pos = (sx, sy); return [("move",) + self.pos]
            return []
        if not self.samples: return []
        # pressure dips briefly mid-press: only call it released after a short quiet spell
        self.quiet += 1
        if self.quiet < 2 or now - self.last_pressed < self.RELEASE_SECS: return []
        was_down, self.down, self.samples, self.quiet = self.down, False, [], 0
        return [("up",) + self.pos] if was_down else []


class ScriptTouch:
    """Presses played back from a file, on the preview clock (see the module docstring)."""

    def __init__(self, path):
        self.presses = []
        for line in open(path):
            line = line.split("#", 1)[0].split()
            if len(line) == 4: self.presses.append(tuple(float(v) for v in line))
        self.active = None
        self.raw = (0, 0)
        self.cfg = {"TOUCH_X_MIN": 0, "TOUCH_X_MAX": 4096, "TOUCH_Y_MIN": 0, "TOUCH_Y_MAX": 4096, "TOUCH_SWAP_XY": 0}

    def poll(self, now):
        if self.active is not None:
            t0, x, y, hold = self.active
            if now >= t0 + hold: self.active = None; return [("up", int(x), int(y))]
            return []
        for p in self.presses:
            if p[0] <= now < p[0] + p[3]:
                self.presses.remove(p); self.active = p; self.raw = (int(p[1] * 4096 / 800), int(p[2] * 4096 / 480))
                return [("down", int(p[1]), int(p[2]))]
        return []


class PipeTouch:
    """Presses from the desktop previewer (tools/preview/preview.py): "down X Y", "move X Y" and
    "up X Y" lines, in screen pixels, from a named pipe (VACATION_TOUCH_PIPE)."""

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.buf = b""
        self.raw = (0, 0)
        self.cfg = {"TOUCH_X_MIN": 0, "TOUCH_X_MAX": 4096, "TOUCH_Y_MIN": 0, "TOUCH_Y_MAX": 4096, "TOUCH_SWAP_XY": 0}

    def poll(self, now=None):
        try: self.buf += os.read(self.fd, 4096)
        except (BlockingIOError, OSError): pass
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            p = line.split()
            if len(p) == 3 and p[0] in (b"down", b"move", b"up"):
                x, y = int(p[1]), int(p[2])
                self.raw = (x * 4096 // 800, y * 4096 // 480)
                out.append((p[0].decode(), x, y))
        return out
