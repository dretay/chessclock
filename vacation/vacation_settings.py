"""The vacation countdown's Settings: opened by pressing and holding the picture for two seconds.

  Page 1  the sail date, and today's date and time (the board has no clock battery)
  Page 2  fireworks: when (random through the night, a nightly show at a set time, both, or off),
          how often the random ones go up, and the show's time
  and a touch calibration screen.

It runs inside the countdown program, drawing with the C library (vacfx.c's vfx_ui_*) from text
pre-drawn on a desktop (tools/themegen/build_ui.py; layout in vacation_layout.py): no Pillow, so
it opens at once. Save writes /etc/vacation.conf (and sets the clock if today's date or time were
changed); Cancel, or a minute and a half untouched, leaves everything as it was.
"""
import calendar, datetime, os

import vacation_layout as L

IDLE_SECS = 90
REPEAT_DELAY, REPEAT_EVERY = 0.5, 0.12


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


def write_conf_value(path, key, value):
    """Change one KEY=VALUE line (or add it), keeping the rest; safe against a power cut mid-write."""
    try: lines = open(path).read().splitlines()
    except OSError: lines = []
    done = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i] = "%s=%s" % (key, value); done = True
    if not done: lines.append("%s=%s" % (key, value))
    tmp = path + ".tmp"
    with open(tmp, "w") as f: f.write("\n".join(lines) + "\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


class Settings:
    def __init__(self, app):
        self.app, self.fx = app, app.fx
        c = app.conf
        try: sail = datetime.date.fromisoformat(c.get("SAIL_DATE", ""))
        except ValueError: sail = datetime.date.today() + datetime.timedelta(days=100)
        now = datetime.datetime.now()
        try: sh, sm = (int(v) for v in c.get("FIREWORKS_SHOW_TIME", "21:00").split(":"))
        except ValueError: sh, sm = 21, 0
        self.v = {"sm": sail.month, "sd": sail.day, "sy": sail.year,
                  "tm": now.month, "td": now.day, "ty": now.year,
                  "hh": now.hour % 12 or 12, "mi": now.minute, "ap": int(now.hour >= 12),
                  "fh": sh % 12 or 12, "fm": sm, "fa": int(sh >= 12)}
        self.mode = c.get("FIREWORKS_MODE", "random")
        try: self.rate = int(c.get("FIREWORKS_EVERY_MIN", "15"))
        except ValueError: self.rate = 15
        self.clock_changed = False
        self.demo = False                  # a fireworks show as soon as Settings closes (Fireworks page)
        self.page = 1; self.pressed = None
        self.cols1 = {}
        for _, top, cols in L.PAGE1_ROWS: self.cols1.update(L.columns(cols, top))
        self.cols2 = L.columns(L.PAGE2_ROW_B[2], L.PAGE2_ROW_B[1])
        self.ids = {}

    # ---------------------------------------------------------------- drawing primitives (all in C)
    def sid(self, key):
        if key not in self.ids: self.ids[key] = self.fx.vfx_ui_find(key.encode())
        return self.ids[key]

    def width(self, font, s):
        k = self.sid("%s|%s" % (font, s))
        if k >= 0: return self.fx.vfx_ui_metric(k, 4)
        return sum(self.fx.vfx_ui_metric(self.sid("%s|%s" % (font, ch)), 4) for ch in s)

    def text(self, font, s, x, base, color, align="l", alpha=255):
        w = self.width(font, s)
        x = x - w if align == "r" else x - w // 2 if align == "m" else x
        k = self.sid("%s|%s" % (font, s))
        if k >= 0: self.fx.vfx_ui_text(k, x, base, rgb(color), alpha); return
        for ch in s:                                    # numbers: digit by digit
            k = self.sid("%s|%s" % (font, ch)); self.fx.vfx_ui_text(k, x, base, rgb(color), alpha)
            x += self.fx.vfx_ui_metric(k, 4)

    def round(self, box, r, color, alpha, line=(255, 255, 255), line_alpha=0):
        self.fx.vfx_ui_round(box[0], box[1], box[2], box[3], r, rgb(color), alpha, rgb(line), line_alpha)

    def bg(self, box, shade=256): self.fx.vfx_ui_bg(box[0], box[1], box[2], box[3], shade)

    def panel(self, box): self.round(box, 16, L.PANEL_FILL, L.PANEL_ALPHA, (255, 255, 255), L.PANEL_LINE_ALPHA)

    def under_panel(self, box):
        """Restore a patch of a panel before redrawing what's on it."""
        self.bg(box); self.round(box, 0, L.PANEL_FILL, L.PANEL_ALPHA)

    # ---------------------------------------------------------------- values
    def text_of(self, k):
        v = self.v[k]
        if k in ("sm", "tm"): return L.MONTHS[v - 1]
        if k in ("mi", "fm"): return "%02d" % v
        if k in ("ap", "fa"): return "PM" if v else "AM"
        return str(v)

    def step(self, k, d):
        v = self.v
        if k in ("sm", "tm"): v[k] = (v[k] - 1 + d) % 12 + 1
        elif k in ("sy", "ty"): v[k] = max(2024, min(2099, v[k] + d))
        elif k in ("hh", "fh"): v[k] = (v[k] - 1 + d) % 12 + 1
        elif k in ("mi", "fm"): v[k] = (v[k] + d) % 60
        elif k in ("ap", "fa"): v[k] ^= 1
        for dk, mk, yk in (("sd", "sm", "sy"), ("td", "tm", "ty")):
            last = calendar.monthrange(v[yk], v[mk])[1]
            if k == dk: v[dk] = (v[dk] - 1 + d) % last + 1
            v[dk] = min(v[dk], last)
        if k in ("tm", "td", "ty", "hh", "mi", "ap"): self.clock_changed = True

    def days_left(self):
        v = self.v
        return (datetime.date(v["sy"], v["sm"], v["sd"]) - datetime.date(v["ty"], v["tm"], v["td"])).days

    # ---------------------------------------------------------------- pages
    def draw_header(self):
        box = (420, 14, L.W - 20, 62); self.bg(box)
        n = self.days_left()
        if n > 0:
            suffix = " day to go" if n == 1 else " days to go"
            sw = self.width("label", suffix)
            self.text("label", suffix, L.W - 36, 46, L.GOLD, "r"); self.text("label", str(n), L.W - 36 - sw, 46, L.GOLD, "r")
        else:
            self.text("label", "Today's the day!" if n == 0 else "Already sailed", L.W - 36, 46, L.GOLD, "r")

    def draw_col(self, k, dim=False):
        cols = self.cols1 if self.page == 1 else self.cols2
        x0, top, x1 = cols[k]; box = (x0, top, x1, top + L.COL_H); cx = (x0 + x1) // 2
        self.under_panel(box)
        self.round(box, 10, (255, 255, 255), 16)
        a = 110 if dim else 255
        for part, y0, y1, arrow_y in (("up", top + 2, top + 36, top + 12), ("down", top + 92, top + 126, top + 102)):
            hot = self.pressed == (part, k)
            if hot: self.round((x0 + 2, y0, x1 - 2, y1), 8, L.GOLD, 90)
            self.fx.vfx_ui_text(self.sid("arrow|" + part), cx - 13, arrow_y, rgb(L.IVORY), 255 if hot else a * 200 // 255)
        self.text("value", self.text_of(k), cx, top + 79, L.IVORY, "m", a)

    def draw_button(self, name):
        x0, y0, x1, y1 = box = (L.PAGE1_BUTTONS if self.page == 1 else L.PAGE2_BUTTONS)[name]
        self.bg((x0 - 2, y0 - 2, x1 + 2, y1 + 2)); hot = self.pressed == name; cx = (x0 + x1) // 2
        if name == "save":
            self.round(box, 14, (238, 206, 138) if hot else L.GOLD, 255)
            self.text("button", "Save", cx, y0 + 38, L.DARK, "m")
        elif name in ("cancel", "back"):
            self.round(box, 14, (255, 255, 255), 60 if hot else 22, (255, 255, 255), 120)
            self.text("button", "Cancel" if name == "cancel" else "‹ Back", cx, y0 + 38, L.IVORY, "m")
        elif name == "demo" and self.demo:                  # armed
            self.round(box, 12, (238, 206, 138) if hot else L.GOLD, 255)
            self.text("small", "Demo show on exit", cx, y0 + 25, L.DARK, "m")
        else:
            self.round(box, 12, (255, 255, 255), 40 if hot else 0, (255, 255, 255), 70)
            label = {"calibrate": "Calibrate touch", "fireworks": "Fireworks ›", "demo": "Demo show"}[name]
            self.text("small", label, cx, y0 + 25, L.DIM, "m")

    def chip_box(self, row, i):
        y = L.PAGE2_CHIP_ROWS[row][1]; x = L.CHIP_X0 + i * (L.CHIP_W + L.CHIP_GAP)
        return (x, y, x + L.CHIP_W, y + L.CHIP_H)

    def draw_chip(self, row, i):
        box = self.chip_box(row, i); value, label = L.PAGE2_CHIP_ROWS[row][2][i]
        on = (self.mode == value) if row == 0 else (self.rate == value)
        hot = self.pressed == ("chip", row, i)
        self.under_panel((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1))
        if on: self.round(box, 12, L.GOLD, 255)
        else: self.round(box, 12, (255, 255, 255), 60 if hot else 18, (255, 255, 255), 70)
        # the random-bursts row is greyed out when there are no random bursts
        live = row == 0 or self.mode in ("random", "both")
        self.text("chip", label, (box[0] + box[2]) // 2, box[1] + 32, L.DARK if on else L.IVORY, "m", 255 if on or live else 120)

    def show_dim(self): return self.mode not in ("show", "both")

    def draw_page(self):
        self.bg((0, 0, L.W, L.H))
        if self.page == 1:
            self.text("title", "Settings", 36, 58, L.IVORY)
            for label, top, _ in L.PAGE1_ROWS:
                self.panel((20, top, L.W - 20, top + 148)); self.text("label", label, 40, top + 84, L.IVORY)
            self.text("small", "date & time", 40, 345, L.DIM)
            for k in self.cols1: self.draw_col(k)
            for b in L.PAGE1_BUTTONS: self.draw_button(b)
        else:
            self.text("title", "Fireworks", 36, 58, L.IVORY)
            self.panel(L.PAGE2_PANEL_A)
            for row, (label, y, opts) in enumerate(L.PAGE2_CHIP_ROWS):
                self.text("label", label, 40, y + 34, L.IVORY)
                for i in range(len(opts)): self.draw_chip(row, i)
            self.text("small", "bursts", 40, L.PAGE2_CHIP_ROWS[1][1] + 54, L.DIM)
            label, top, _ = L.PAGE2_ROW_B
            self.panel((20, top, L.W - 20, top + 148)); self.text("label", label, 40, top + 84, L.IVORY)
            self.text("small", "nightly show", 40, top + 109, L.DIM)
            for k in self.cols2: self.draw_col(k, self.show_dim())
            for b in L.PAGE2_BUTTONS: self.draw_button(b)
        self.draw_header()
        self.fx.vfx_ui_flush()

    # ---------------------------------------------------------------- touch
    def hit(self, x, y):
        """Generous on purpose: a resistive screen's aim drifts."""
        if self.page == 1:
            if y >= 372: return "cancel" if x < 226 else "calibrate" if x < 400 else "fireworks" if x < 574 else "save"
            for _, top, cols in L.PAGE1_ROWS:
                if top <= y < top + 148:
                    for c in cols:
                        if c and self.cols1[c[0]][0] - 6 <= x < self.cols1[c[0]][2] + 6:
                            return ("up", c[0]) if y < top + 74 else ("down", c[0])
            return None
        if y >= 382: return "back" if x < 268 else "demo" if x < 532 else "save"
        x0a, y0a, x1a, y1a = L.PAGE2_PANEL_A
        if y0a <= y < y1a and x >= L.CHIP_X0 - 20:
            row = 0 if y < 144 else 1; n = len(L.PAGE2_CHIP_ROWS[row][2])
            i = (x - L.CHIP_X0 + L.CHIP_GAP // 2) // (L.CHIP_W + L.CHIP_GAP)
            return ("chip", row, max(0, min(n - 1, i)))
        top = L.PAGE2_ROW_B[1]
        if top <= y < top + 148:
            for k, (c0, t, c1) in self.cols2.items():
                if c0 - 6 <= x < c1 + 6: return ("up", k) if y < top + 74 else ("down", k)
        return None

    def is_arrow(self, target): return isinstance(target, tuple) and target[0] in ("up", "down")

    def press(self, target):
        """What a press does straight away (arrows step at once, and repeat while held)."""
        if self.is_arrow(target):
            self.step(target[1], 1 if target[0] == "up" else -1)
            self.draw_col(target[1], self.page == 2 and self.show_dim())
            if self.page == 1:
                for k in ("sd", "td"): self.draw_col(k)
            self.draw_header()
        elif isinstance(target, tuple) and target[0] == "chip": self.draw_chip(target[1], target[2])
        elif target: self.draw_button(target)

    def release(self, target, x, y):
        """Returns "save" or "cancel" when Settings should close."""
        again = self.hit(x, y) == target
        if self.is_arrow(target):
            self.draw_col(target[1], self.page == 2 and self.show_dim()); return None
        if isinstance(target, tuple) and target[0] == "chip":
            if again:
                row, i = target[1], target[2]; value = L.PAGE2_CHIP_ROWS[row][2][i][0]
                if row == 0: self.mode = value
                else: self.rate = value
                for r, (_, _, opts) in enumerate(L.PAGE2_CHIP_ROWS):
                    for j in range(len(opts)): self.draw_chip(r, j)
                for k in self.cols2: self.draw_col(k, self.show_dim())
            else: self.draw_chip(target[1], target[2])
            return None
        if target: self.draw_button(target)
        if not again: return None
        if target in ("save", "cancel"): return target
        if target == "demo": self.demo = not self.demo; self.draw_button("demo"); return None
        if target == "fireworks": self.page = 2; self.draw_page()
        elif target == "back": self.page = 1; self.draw_page()
        elif target == "calibrate": self.calibrate(); self.draw_page()
        return None

    def run(self):
        app, fx = self.app, self.fx
        if fx.vfx_ui_open(app.ui_dir.encode(), app.theme_dir.encode()) != 0:
            print("settings: couldn't load the Settings images", flush=True); return False
        self.draw_page()
        tp = app.touch
        opened = last_touch = app.now(); repeat_at = None; result = None; ignoring = False
        while result is None and app.running:
            now = app.now()
            for ev, x, y in (tp.poll(now) if tp else []):
                if ev == "down" and now - opened < 1.0: ignoring = True      # the finger that opened Settings
                if ignoring:
                    if ev == "up": ignoring = False
                    continue
                last_touch = now
                if ev == "down":
                    self.pressed = self.hit(x, y)
                    print("settings: press at (%d, %d): %s" % (x, y, self.pressed), flush=True)
                    self.press(self.pressed)
                    repeat_at = now + REPEAT_DELAY if self.is_arrow(self.pressed) else None
                elif ev == "up":
                    was, self.pressed, repeat_at = self.pressed, None, None
                    result = self.release(was, x, y)
            if repeat_at and now >= repeat_at and self.pressed:
                repeat_at = now + REPEAT_EVERY; self.press(self.pressed)
            fx.vfx_ui_flush()
            if now - last_touch > IDLE_SECS: result = "cancel"
            app.tick()
        if result == "save": self.save()
        self.closing(result == "save")
        fx.vfx_ui_close()
        return result == "save"

    def closing(self, saved):
        """Say so at once, then back to the countdown."""
        box = (L.W // 2 - 170, L.H // 2 - 50, L.W // 2 + 170, L.H // 2 + 50)
        self.round(box, 18, (8, 14, 30), 240, L.GOLD, 160)
        self.text("label", "Saved" if saved else "No changes", L.W // 2, box[1] + 50, L.GOLD if saved else L.IVORY, "m")
        self.text("small", "fireworks!" if self.demo else "back to the countdown", L.W // 2, box[1] + 78, L.DIM, "m")
        self.fx.vfx_ui_flush()
        until = self.app.now() + 0.7
        while self.app.now() < until: self.app.tick()

    # ---------------------------------------------------------------- touch calibration
    TARGETS = [(60, 60), (740, 60), (740, 420), (60, 420)]

    def draw_target(self, k, note=None):
        self.bg((0, 0, L.W, L.H), 128)
        self.text("title", "Touch calibration", L.W // 2, 200, L.IVORY, "m")
        self.text("label", note or "Tap the centre of the cross (%d of 4)" % (k + 1), L.W // 2, 250, L.GOLD, "m")
        x, y = self.TARGETS[k]; self.fx.vfx_ui_text(self.sid("cross"), x, y, rgb(L.IVORY), 255)
        self.fx.vfx_ui_flush()

    def calibrate(self):
        """Four crosses, one at a time; from where the touch chip says they were, work out its range."""
        app, tp = self.app, self.app.touch
        if not tp: return
        raws, k = [], 0; self.draw_target(0)
        start = app.now(); last_up = -1e9; taking = False
        while k < 4 and app.running:
            now = app.now()
            for ev, x, y in tp.poll(now):
                if ev == "down":
                    # a resistive screen can report a second press as the finger lifts: ignore presses right
                    # after a release, and any that land where the last cross was
                    far = not raws or abs(tp.raw[0] - raws[-1][0]) + abs(tp.raw[1] - raws[-1][1]) > 800
                    taking = now - last_up > 0.2 and far
                    print("settings: calibration point %d raw %s%s" % (k + 1, tp.raw, "" if taking else " (ignored)"), flush=True)
                    if taking: raws.append(tp.raw)
                if ev == "up":
                    last_up = now
                    if taking:
                        taking = False; k += 1
                        if k < 4: self.draw_target(k)
            if now - start > 60: return                                    # given up on: leave it as it was
            app.tick()
        if k < 4: return
        (ax, ay), (bx, by), (cx, cy), (dx, dy) = raws
        swap = abs((by + cy) - (ay + dy)) > abs((bx + cx) - (ax + dx))      # moving right changed the chip's y
        if swap: (ax, ay), (bx, by), (cx, cy), (dx, dy) = (ay, ax), (by, bx), (cy, cx), (dy, dx)
        px = ((bx + cx) - (ax + dx)) / 2 / (740 - 60); py = ((cy + dy) - (ay + by)) / 2 / (420 - 60)
        ok = 2 <= abs(px) <= 15 and 2 <= abs(py) <= 15                     # about 5 and 8.5 raw units a pixel
        sx, sy = abs(bx + cx - ax - dx), abs(cy + dy - ay - by)
        ok = ok and abs(ax - dx) < 0.25 * sx and abs(bx - cx) < 0.25 * sx and abs(ay - by) < 0.25 * sy and abs(cy - dy) < 0.25 * sy
        if ok:
            x_min = (ax + dx) / 2 - 60 * px; y_min = (ay + by) / 2 - 60 * py
            cal = {"TOUCH_X_MIN": round(x_min), "TOUCH_X_MAX": round(x_min + L.W * px), "TOUCH_Y_MIN": round(y_min),
                   "TOUCH_Y_MAX": round(y_min + L.H * py), "TOUCH_SWAP_XY": int(swap)}
            for key, v in cal.items(): write_conf_value(app.conf_path, key, v)
            tp.cfg.update(cal)
            print("settings: touch calibrated:", cal, flush=True)
        self.draw_target(3, "Calibrated" if ok else "That didn't look right: nothing changed")
        until = app.now() + 1.5
        while app.now() < until: app.tick()

    # ---------------------------------------------------------------- saving
    def save(self):
        v, path = self.v, self.app.conf_path
        write_conf_value(path, "SAIL_DATE", "%04d-%02d-%02d" % (v["sy"], v["sm"], v["sd"]))
        write_conf_value(path, "FIREWORKS_MODE", self.mode)
        write_conf_value(path, "FIREWORKS_EVERY_MIN", self.rate)
        write_conf_value(path, "FIREWORKS_SHOW_TIME", "%02d:%02d" % (v["fh"] % 12 + (12 if v["fa"] else 0), v["fm"]))
        if self.clock_changed:
            h = v["hh"] % 12 + (12 if v["ap"] else 0)
            stamp = "%04d-%02d-%02d %02d:%02d:00" % (v["ty"], v["tm"], v["td"], h, v["mi"])
            if self.app.sim: print("settings: (preview) would set the clock to", stamp, flush=True)
            else: os.system("date -s '%s' >/dev/null" % stamp); self.app.save_clock()
        print("settings: saved", flush=True)
