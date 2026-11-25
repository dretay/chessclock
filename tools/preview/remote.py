"""The previewer's Controls set to Device: the same live controls (time of day, fireworks, the nightly
show, birds, the lights' pattern, stay on the scene) for the countdown running on the board, written over
its USB console into /tmp/countdown-live.json (in RAM: a reboot forgets it), which the countdown looks at a
few times a second (apps/countdown/vacation.py REMOTE_LIVE). No network, nothing listening on the board.

One-shot controls (fireworks, show, birds) are times in ms: the countdown fires each when it's larger than
the last, so a new session never sets one off by itself. Leaving Device puts the board back as it was
(its own clock, its screens in turn, every pattern), one-shots aside.

Pushes are merged (a slider dragged sends the last place only); the port is let go after a few idle
seconds, so deploy.py and the other board tools can have it.
"""
import json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "board"))
LIVE = "/tmp/countdown-live.json"
# switching the device's app: as `app NAME` does, with the new app's splash (its picture, "Starting" and the
# pulsing dots, as at boot) put up between stopping the old one and starting it, so the screen says what's
# happening for the few seconds it takes (the countdown takes the dots down when it draws). Exit 3: not
# installed. (Here rather than only in the board's `app`: that's in the base system, which needs a reflash.)
SWITCH = ('( [ -x /apps/NAME/run ] || exit 3; [ "$(cat /apps/current 2>/dev/null)" = NAME ] && exit 0; '
          '/etc/init.d/S99app stop >/dev/null 2>&1; '
          '( cd /apps/NAME && [ -r splash.sh ] && . ./splash.sh ) >/dev/null 2>&1; '
          'echo NAME > /apps/current.tmp && mv /apps/current.tmp /apps/current && sync; '
          '/etc/init.d/S99app start >/dev/null 2>&1 )')
IDLE_SECS = 4


class Remote:
    def __init__(self):
        self.state, self.dirty, self.note = {}, False, ""
        self.want_app = None                                                # (an app to switch the device to: `app NAME`)
        self.cv = threading.Condition()
        self.port = None
        threading.Thread(target=self.run, daemon=True).start()

    def set(self, **kw):
        with self.cv: self.state.update(kw); self.dirty = True; self.cv.notify()

    def switch_app(self, name):
        """The device to that app too (`app NAME`: now, and at every boot), if it's installed there."""
        if not name.replace("-", "").isalnum(): return
        with self.cv: self.want_app = name; self.dirty = True; self.cv.notify()

    def fire(self, key): self.set(**{key: int(time.time() * 1000)})

    def reset(self):
        """The board back to itself: its own clock, its screens in turn, every pattern."""
        self.set(hour=None, stay=False, pattern=-1)

    def run(self):
        while True:
            with self.cv:
                if not self.dirty:
                    self.cv.wait(IDLE_SECS)
                    if not self.dirty: self.close(); continue
                st, app, self.dirty, self.want_app = dict(self.state), self.want_app, False, None
            if app: self.push(st, app)
            else: self.push(st)

    def close(self):
        if self.port:
            try: self.port.close()
            except Exception: pass
            self.port = None

    def run_cmd(self, command, secs=5):
        """A shell command on the board: its exit status (None: no answer). Reads only until its end marker
        and that line's end (a slider's pushes come one after another)."""
        p = self.port; p.reset_input_buffer()
        p.write(('%s; echo "__RM""DONE $?"\n' % command).encode())      # (split: the echoed command doesn't match)
        out, end = b"", time.time() + secs
        while time.time() < end:
            out += p.read(4096)
            i = out.find(b"__RMDONE ")
            if i >= 0 and b"\n" in out[i:]:
                try: return int(out[i + 9:].split()[0])
                except ValueError: return None
        return None

    def push(self, st, app=None):
        import boardlib, serial
        try:
            if not self.port:
                dev = boardlib.board_usb_port()
                if not dev: self.note = "No device on USB (its micro-USB port, plugged into this Mac)"; return
                self.port = serial.Serial(dev, boardlib.BAUD, timeout=0.02)
                boardlib.login(self.port)
            if app:                                                        # (first the app: it reads the controls as it starts)
                self.note = "Switching the device to %s…" % app
                status = self.run_cmd(SWITCH.replace("NAME", app), 40)
                if status == 3: self.note = "%s isn't installed on the device (Scene Builder: Install on the device)" % app; return
                if status != 0: self.note = "The device didn't switch to %s" % app; return
            js = json.dumps(st, separators=(",", ":"))                       # (no ' in it: numbers, true/false, null)
            status = self.run_cmd("printf '%%s' '%s' > %s.tmp && mv %s.tmp %s" % (js, LIVE, LIVE, LIVE))
            self.note = ("On the device" + (": %s" % app if app else "")) if status == 0 else "The device didn't take it" + ("" if status is None else " (%d)" % status)
        except (Exception, SystemExit) as e:
            self.close(); self.note = "The device: %s" % e
