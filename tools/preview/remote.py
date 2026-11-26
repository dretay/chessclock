"""The previewer's Controls set to Device: the same live controls (time of day, fireworks, the nightly
show, birds, fireflies, the lights' pattern, stay on the scene) for the countdown running on the board, written over
its USB console into /tmp/countdown-live.json (in RAM: a reboot forgets it), which the countdown looks at a
few times a second (apps/countdown/vacation.py REMOTE_LIVE). No network, nothing listening on the board.

One-shot controls (fireworks, show, birds, fireflies) are times in ms: the countdown fires each when it's larger than
the last, so a new session never sets one off by itself. Leaving Device puts the board back as it was
(its own clock, its screens in turn, every pattern), one-shots aside.

Pushes are merged (a slider dragged sends the last place only); the port is let go after a few idle
seconds, so deploy.py and the other board tools can have it.

Mirror (the preview window in Remote): the device's screen, pulled over the same console with the system
package's fbgrab (half size, compressed; one line when nothing changed) about once a second, handed to
on_frame as an 800x480 BGRX picture; and the window's presses (touch()), appended to the device's
/tmp/remote-touch, which its apps read beside the touch screen (apps/system/vacation_touch.py). Presses go
first: a frame waits. While mirroring, the port stays open.
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
REMOTE_TOUCH = "/tmp/remote-touch"
FBGRAB = "/apps/system/fbgrab"
FBGRAB_JPEG = "/apps/system/fbgrab-jpeg"          # (a JPEG, a fifth the size: when the base system has libjpeg)


class Remote:
    def __init__(self):
        self.state, self.dirty, self.note = {}, False, ""
        self.want_app = None                                                # (an app to switch the device to: `app NAME`)
        self.mirror, self.touches, self.on_frame = False, [], None          # (the window showing the device: Mirror above)
        self.grabber = FBGRAB_JPEG
        self.full_at = 0.0                     # (when a whole picture was last asked for, not "the same as before")
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

    def set_mirror(self, on):
        """The mirror on or off; on, the countdown holds still (live "still": drawn only when something changes),
        so there's little to send and the frames come quickly."""
        with self.cv:
            self.mirror = bool(on); self.state["still"] = bool(on); self.dirty = True
            self.full_at = 0.0                  # (the window starts empty: the first picture whole, whatever fbgrab last sent)
            self.cv.notify()

    def touch(self, line):
        """A press from the window ("down X Y", "move X Y", "up X Y"), for the device."""
        p = line.split()
        if len(p) != 3 or p[0] not in ("down", "move", "up"): return
        with self.cv:
            if p[0] == "move" and self.touches and self.touches[-1].startswith("move"): self.touches[-1] = line   # (the last place)
            else: self.touches.append(" ".join(p))
            self.cv.notify()

    def reset(self):
        """The board back to itself: its own clock, its screens in turn, every pattern; no mirror."""
        self.set_mirror(False)
        self.set(hour=None, stay=False, pattern=-1)

    def run(self):
        while True:
            with self.cv:
                if not (self.dirty or self.touches):
                    self.cv.wait(0.02 if self.mirror else IDLE_SECS)       # (mirroring: the next frame at once; a press wakes it)
                    if not (self.dirty or self.touches or self.mirror): self.close(); continue
                dirty, st, app, self.dirty, self.want_app = self.dirty, dict(self.state), self.want_app, False, None
                touches, self.touches = self.touches, []
            if dirty: self.push(st, app)
            if touches: self.send_touches(touches)
            elif self.mirror and not dirty: self.grab()

    def connect(self):
        import boardlib, serial
        if self.port: return True
        dev = boardlib.board_usb_port()
        if not dev: self.note = "No device on USB (its micro-USB port, plugged into this Mac)"; return False
        self.port = serial.Serial(dev, boardlib.BAUD, timeout=0.02)
        boardlib.login(self.port)
        return True

    def send_touches(self, lines):
        try:
            if not self.connect(): return
            args = " ".join("'%s'" % l for l in lines)                       # (only "down 12 34"-like lines: no ' in them)
            self.run_cmd("f=%s; [ -f $f ] && [ $(wc -c <$f) -gt 65536 ] && : >$f; printf '%%s\\n' %s >>$f" % (REMOTE_TOUCH, args))
        except (Exception, SystemExit) as e:
            self.close(); self.note = "The device: %s" % e

    def grab(self):
        """One look at the device's screen (fbgrab): to on_frame, unless it's the same as the last."""
        import base64, zlib
        try:
            if not self.connect(): time.sleep(1); return
            # (ahead of the countdown's drawing: it takes most of the CPU, and fbgrab waited half its time for it)
            # (fbgrab answers FBSAME for the picture it last sent, perhaps to another session: the first one, and
            # one every 15 s, whole all the same)
            full = time.time() - self.full_at > 15
            if full: self.full_at = time.time()
            # (and the live controls touched, renewing "still": without it, the countdown moves again after a while)
            renew = "touch %s; " % LIVE if self.state.get("still") else ""
            status, out = self.run_out(renew + ("rm -f /tmp/fbgrab.last; " if full else "") + "nice -n -15 " + self.grabber, 15)
            if status == 127 or b"not found" in out or b"error while loading" in out:
                if self.grabber == FBGRAB_JPEG: self.grabber = FBGRAB; return   # (no libjpeg on the device yet: the bigger kind)
                self.note = "The device's system package is too old to show its screen: update it (Get apps, or Install)"; time.sleep(3); return
            if b"FBSAME" in out or status != 0: return
            i = max(out.find(b"FBGRAB "), out.find(b"FBJPEG ")); j = out.find(b"FBEND")
            if i < 0 or j < 0: return
            head, body = out[i:j].split(b"\n", 1)
            kind = head.split()[0]
            w, h, n = (int(v) for v in head.split()[1:4])
            data = base64.b64decode(b"".join(body.split()))
            if len(data) != n: return                                       # (a garbled read: the next one)
            from PIL import Image
            if kind == b"FBJPEG":
                import io; img = Image.open(io.BytesIO(data)).convert("RGB")
            else:
                img = Image.frombytes("RGB", (w, h), zlib.decompress(data), "raw", "BGR;16")
            img = img.resize((800, 480), Image.BILINEAR)
            if self.on_frame: self.on_frame(img.tobytes("raw", "BGRX"))
            self.note = "Showing the device's screen: clicks and presses are touches on it"
        except (Exception, SystemExit) as e:
            self.close(); self.note = "The device: %s" % e

    def release(self, secs=4):
        """The preview quitting: the device back to itself (the scene moving again) before the port is let go."""
        self.reset()
        end = time.time() + secs
        while time.time() < end and (self.dirty or self.mirror): time.sleep(0.1)
        time.sleep(0.5)

    def close(self):
        if self.port:
            try: self.port.close()
            except Exception: pass
            self.port = None

    def run_cmd(self, command, secs=5):
        """A shell command on the board: its exit status (None: no answer). Reads only until its end marker
        and that line's end (a slider's pushes come one after another)."""
        return self.run_out(command, secs)[0]

    def run_out(self, command, secs=5):
        """A shell command on the board: (its exit status or None, what it printed, with the echoed command)."""
        p = self.port; p.reset_input_buffer()
        p.write(('%s; echo "__RM""DONE $?"\n' % command).encode())      # (split: the echoed command doesn't match)
        out, end = b"", time.time() + secs
        while time.time() < end:
            out += p.read(65536)
            i = out.find(b"__RMDONE ")
            if i >= 0 and b"\n" in out[i:]:
                try: return int(out[i + 9:].split()[0]), out[:i]
                except ValueError: return None, out[:i]
        return None, out

    def push(self, st, app=None):
        try:
            if not self.connect(): return
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
