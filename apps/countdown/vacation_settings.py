"""The countdown's Settings: opened by pressing and holding the picture for two seconds.

  Page 1  the trip's date (the module's label for it: "Sail date", "Park day"), and today's date and time
          (the board has no clock battery)
  Page 2  fireworks: when (random through the night, a nightly show at a set time, both, or off),
          how often the random ones go up, and the show's time
  Page 3  the theme's own settings (the app's, from its app.json "settings": the cruise's
          ship to follow on the map, the castle's rides to show), as chips, a page at a time
  Page 4  WiFi: the networks in range, and which one the board is on (vacation_wifi.py); tapping one
          opens page 5, a keyboard for its password. Joining saves it on the board straight away.
  and a touch calibration screen.

It runs inside the countdown program, drawing with the C library (vacfx.c's vfx_ui_*) from text
pre-drawn on a desktop (tools/themegen/build_ui.py; layout in vacation_layout.py): no Pillow, so
it opens at once. Save writes vacation.conf (and sets the clock if today's date or time were
changed); Cancel, or a minute and a half untouched, leaves everything as it was.
"""
import calendar, datetime, json, os, threading, time

import vacation_layout as L
import vacation_wifi as wifi
from vacation_text import Text, plain

IDLE_SECS = 90
REPEAT_DELAY, REPEAT_EVERY = 0.5, 0.12


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


PICKER = os.environ.get("APP_PICKER") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "pick")   # the app picker (picker.py; APP_PICKER: the previewer's)


def has_picker(): return os.access(PICKER, os.X_OK) and not os.environ.get("VACATION_SIM_CLOCK")


def open_picker():
    """Settings > Apps: the picker, in a session of its own (it stops this app, so it mustn't be its child)."""
    import subprocess
    try: subprocess.Popen([PICKER], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e: print("settings: no app picker: %s" % e, flush=True)


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
        try: sail = datetime.date.fromisoformat(c.get("TRIP_DATE") or c.get("SAIL_DATE", ""))
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
        self.load_theme_setting(app)
        mod = getattr(app, "module", None)
        self.countdown = (mod.meta.get("countdown") or {}) if mod else {}
        self.clock_changed = False
        self.demo = False                  # a fireworks show as soon as Settings closes (Fireworks page)
        self.page = 1; self.pressed = None
        # WiFi (pages 4 and 5)
        self.wpa = None; self.nets = []; self.job = None; self.scanning = False
        self.wifi_state = ("off", ""); self.wifi_msg = ""; self.next_status = 0.0
        self.joining = None                # (ssid, give up at) while connecting
        self.join_ssid = ""; self.typed = ""; self.kb_layer = "letters"; self.kb_shift = False; self.keys = []
        self.cols1 = {}
        for _, top, cols in L.PAGE1_ROWS: self.cols1.update(L.columns(cols, top))
        self.cols2 = L.columns(L.PAGE2_ROW_B[2], L.PAGE2_ROW_B[1])
        self.ids = {}; self.txt = Text(self.fx)

    # ---------------------------------------------------------------- the theme's setting (page 3)
    def load_theme_setting(self, app):
        """The app's first setting (app.json "settings"): its options, and what's chosen.
        "one": pick one; "many": pick any (stored joined with |, as names may have commas). Options are
        listed in app.json, or come from a file the app's service writes ("options_from", e.g.
        waits.json's rides), else that file's *_example.json beside the module."""
        mod = getattr(app, "module", None)
        specs = (mod.meta.get("settings") or []) if mod else []
        self.theme = specs[0] if specs else None; self.theme_opts = []; self.theme_pick = set(); self.theme_page = 0
        self.module_name = mod.name if mod else ""
        self.short = {plain(k): v for k, v in ((mod.meta.get("short_names") or {}) if mod else {}).items()}
        if not self.theme: return
        sp = self.theme; key = sp["key"]
        if "options" in sp: opts = list(sp["options"])
        else:
            src = sp.get("options_from", ""); stem, ext = os.path.splitext(src); opts = []
            for path in (os.path.join(mod.data_dir, src), os.path.join(mod.dir, stem + "_example" + ext)):
                try: opts = sorted({r["name"] for r in json.load(open(path)).get("rides", [])}, key=lambda n: self.short.get(plain(n), plain(n)).strip('"').lower()); break
                except (OSError, ValueError, KeyError, TypeError): pass
        self.theme_opts = opts
        cur = app.conf.get(key, "")
        if sp.get("type") == "many": self.theme_pick = {v for v in cur.split("|") if v in opts}
        else:
            v = cur or sp.get("default") or (app.conf.get(sp["fallback"], "") if sp.get("fallback") else "")
            self.theme_pick = {v if v in opts else (opts[0] if opts else "")}

    def opt_label(self, name):
        sp = self.theme or {}; s = self.short.get(plain(name), plain(name)).strip('"')
        strip = sp.get("strip", "")
        return s[len(strip):] if strip and s.startswith(strip) else s

    def per_page(self): return L.PAGE3_GRID[2] * L.PAGE3_GRID[3]
    def pages(self): return max(1, -(-len(self.theme_opts) // self.per_page()))

    def opt_box(self, i):
        x0, y0, cols, rows, ch, gap = L.PAGE3_GRID
        cw = (L.W - 2 * x0 - (cols - 1) * gap) // cols
        k = i % self.per_page(); c, r = k % cols, k // cols
        x = x0 + c * (cw + gap); y = y0 + r * (ch + gap)
        return (x, y, x + cw, y + ch)

    def draw_opt(self, i):
        box = self.opt_box(i); name = self.theme_opts[i]
        on = name in self.theme_pick; hot = self.pressed == ("opt", i)
        self.under_panel((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1))
        if on: self.round(box, 12, L.GOLD, 255)
        else: self.round(box, 12, (255, 255, 255), 60 if hot else 18, (255, 255, 255), 70)
        label = self.opt_label(name); t = self.txt
        font = "chip" if t.sid("chip|" + label) >= 0 else "small"            # (pre-drawn: the cruise's ships)
        t.draw(font, t.fit(font, label, box[2] - box[0] - 20), (box[0] + box[2]) // 2, box[1] + (27 if font == "chip" else 25),
               L.DARK if on else L.IVORY, "m")

    def draw_theme_page(self):
        self.text("title", "Theme settings", 36, 58, L.IVORY)
        self.panel(L.PAGE3_PANEL)
        if not self.theme or not self.theme_opts:
            self.txt.draw("label", "Nothing to set for this theme" if not self.theme else "Nothing to choose from yet",
                          L.W // 2, (L.PAGE3_PANEL[1] + L.PAGE3_PANEL[3]) // 2, L.DIM, "m")
        else:
            w = self.txt.draw("label", plain(self.theme.get("label", "")), 40, L.PAGE3_LABEL_Y, L.IVORY)
            if self.theme.get("note"): self.txt.draw("small", plain(self.theme["note"]), 40 + w + 14, L.PAGE3_LABEL_Y, L.DIM)
            first = self.theme_page * self.per_page()
            for i in range(first, min(len(self.theme_opts), first + self.per_page())): self.draw_opt(i)
            if self.pages() > 1:
                self.txt.draw("small", "%d of %d" % (self.theme_page + 1, self.pages()), 400, 437, L.DIM, "m")
        for b in L.PAGE3_BUTTONS:
            if b in ("prev", "next") and self.pages() < 2: continue
            self.draw_button(b)

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
            after = self.countdown.get("after", "Already sailed")
            if n == 0: self.text("label", "Today's the day!", L.W - 36, 46, L.GOLD, "r")
            else: self.txt.draw("label", after, L.W - 36, 46, L.GOLD, "r")

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
        if name == "apps": x0, y0, x1, y1 = box = L.PAGE1_APPS
        else: x0, y0, x1, y1 = box = {1: L.PAGE1_BUTTONS, 2: L.PAGE2_BUTTONS, 3: L.PAGE3_BUTTONS, 4: L.WIFI_BUTTONS, 5: L.KB_BUTTONS}[self.page][name]
        self.bg((x0 - 2, y0 - 2, x1 + 2, y1 + 2)); hot = self.pressed == name; cx = (x0 + x1) // 2
        if name in ("save", "kb_join"):
            self.round(box, 14, (238, 206, 138) if hot else L.GOLD, 255)
            self.text("button", "Save" if name == "save" else "Join", cx, y0 + 38, L.DARK, "m")
        elif name in ("cancel", "back", "kb_cancel"):
            self.round(box, 14, (255, 255, 255), 60 if hot else 22, (255, 255, 255), 120)
            self.text("button", "‹ Back" if name == "back" else "Cancel", cx, y0 + 38, L.IVORY, "m")
        elif name == "forget" and self.wifi_state[0] == "off":
            pass                                            # (nothing to forget)
        elif name == "demo" and self.demo:                  # armed
            self.round(box, 12, (238, 206, 138) if hot else L.GOLD, 255)
            self.text("small", "Demo show on exit", cx, y0 + 25, L.DARK, "m")
        else:
            self.round(box, 12, (255, 255, 255), 40 if hot else 0, (255, 255, 255), 70)
            if name in ("prev", "next"):
                self.text("button", "‹" if name == "prev" else "›", cx, y0 + 30, L.IVORY if self.pages() > 1 else L.DIM, "m"); return
            label = {"calibrate": "Touch", "fireworks": "Fireworks ›", "theme": "Theme ›", "wifi": "WiFi ›", "demo": "Demo show", "apps": "Apps ›",
                     "rescan": "Rescan", "forget": "Forget network"}[name]
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
            for k, (label, top, _) in enumerate(L.PAGE1_ROWS):
                if k == 0: label = self.countdown.get("date_label", label)        # the module's: "Sail date", "Park day"
                self.panel((20, top, L.W - 20, top + 148)); self.txt.draw("label", label, 40, top + 84, L.IVORY)
            self.text("small", "date & time", 40, 345, L.DIM)
            for k in self.cols1: self.draw_col(k)
            for b in L.PAGE1_BUTTONS: self.draw_button(b)
            if has_picker(): self.draw_button("apps")
        elif self.page == 4:
            self.draw_wifi_page()
        elif self.page == 5:
            self.draw_keyboard_page()
        elif self.page == 3:
            self.draw_theme_page()
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
            if y >= 372: return next(name for edge, name in L.PAGE1_SPLITS if x < edge)
            ax0, _, ax1, ay1 = L.PAGE1_APPS
            if y < ay1 + 12 and ax0 - 12 <= x < ax1 + 12 and has_picker(): return "apps"
            for _, top, cols in L.PAGE1_ROWS:
                if top <= y < top + 148:
                    for c in cols:
                        if c and self.cols1[c[0]][0] - 6 <= x < self.cols1[c[0]][2] + 6:
                            return ("up", c[0]) if y < top + 74 else ("down", c[0])
            return None
        if self.page == 4: return self.hit_wifi(x, y)
        if self.page == 5: return self.hit_keyboard(x, y)
        if self.page == 3:
            if y >= 400:
                if x < 268: return "back"
                if x >= 532: return "save"
                if self.pages() < 2: return None
                return "prev" if x < 400 else "next"
            x0, y0, cols, rows, ch, gap = L.PAGE3_GRID
            if y >= y0 - gap // 2 and self.theme_opts:
                cw = (L.W - 2 * x0 - (cols - 1) * gap) // cols
                c = max(0, min(cols - 1, (x - x0 + gap // 2) // (cw + gap))); r = (y - y0 + gap // 2) // (ch + gap)
                i = self.theme_page * self.per_page() + r * cols + c
                if 0 <= r < rows and i < len(self.theme_opts): return ("opt", i)
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
        elif isinstance(target, tuple) and target[0] == "opt": self.draw_opt(target[1])
        elif isinstance(target, tuple) and target[0] == "net": self.draw_net_row(target[1])
        elif isinstance(target, tuple) and target[0] == "key": self.draw_key(target[1])
        elif target: self.draw_button(target)

    def release(self, target, x, y):
        """Returns "save" or "cancel" when Settings should close."""
        again = self.hit(x, y) == target
        if self.is_arrow(target):
            self.draw_col(target[1], self.page == 2 and self.show_dim()); return None
        if isinstance(target, tuple) and target[0] == "key":       # a key types as it's let go (wherever the finger drifted)
            self.type_key(target[1]); return None
        if isinstance(target, tuple) and target[0] == "net":
            self.draw_net_row(target[1])
            if again and target[1] < len(self.nets): self.pick_network(self.nets[target[1]])
            return None
        if isinstance(target, tuple) and target[0] == "opt":
            name = self.theme_opts[target[1]]
            if again:
                if self.theme.get("type") == "many": self.theme_pick ^= {name}
                else: self.theme_pick = {name}
            first = self.theme_page * self.per_page()
            for i in range(first, min(len(self.theme_opts), first + self.per_page())): self.draw_opt(i)
            return None
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
        if target == "apps": return "apps"
        if target == "fireworks": self.page = 2; self.draw_page()
        elif target == "theme": self.page = 3; self.draw_page()
        elif target in ("prev", "next"):
            self.theme_page = (self.theme_page + (1 if target == "next" else -1)) % self.pages(); self.draw_page()
        elif target == "wifi": self.page = 4; self.draw_page(); self.start_scan()
        elif target == "rescan": self.start_scan()
        elif target == "forget" and self.wifi_state[0] != "off": self.start_job("forget", lambda w: w.forget())
        elif target == "kb_cancel": self.page = 4; self.draw_page()
        elif target == "kb_join": self.join(self.join_ssid, self.typed)
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
                    # (never log the keyboard's keys, or where they are: that would put a typed
                    # WiFi password in the log)
                    if not (isinstance(self.pressed, tuple) and self.pressed[:1] == ("key",)):
                        print("settings: press at (%d, %d): %s" % (x, y, self.pressed), flush=True)
                    self.press(self.pressed)
                    repeat_at = now + REPEAT_DELAY if self.is_arrow(self.pressed) else None
                elif ev == "up":
                    was, self.pressed, repeat_at = self.pressed, None, None
                    result = self.release(was, x, y)
            if self.page in (4, 5): self.wifi_tick(now)
            if repeat_at and now >= repeat_at and self.pressed:
                repeat_at = now + REPEAT_EVERY; self.press(self.pressed)
            fx.vfx_ui_flush()
            if now - last_touch > IDLE_SECS: result = "cancel"
            app.tick()
        if self.wpa: self.wpa.close()
        if result == "apps":
            if not self.opening_apps():                                   # the picker stopped us: leave its screen be
                fx.vfx_ui_close(); return False
            result = "cancel"                                             # (it didn't start: back to the countdown)
        if result == "save": self.save()
        self.closing(result == "save")
        fx.vfx_ui_close()
        return result == "save"

    def opening_apps(self, wait=30.0):
        """Settings > Apps: say so, start the picker, and stay as we are until it stops this app (it
        takes a few seconds to start; S99app's stop sets app.running to False); True if it didn't, after
        wait seconds."""
        box = (L.W // 2 - 170, L.H // 2 - 50, L.W // 2 + 170, L.H // 2 + 50)
        self.round(box, 18, (8, 14, 30), 240, L.GOLD, 160)
        self.text("label", "Opening apps...", L.W // 2, box[1] + 50, L.IVORY, "m")
        self.text("small", "one moment", L.W // 2, box[1] + 78, L.DIM, "m")
        self.fx.vfx_ui_flush()
        open_picker()
        until = self.app.now() + wait
        while self.app.running and self.app.now() < until: self.app.tick()
        return self.app.running

    def closing(self, saved):
        """Say so at once, then back to the countdown."""
        box = (L.W // 2 - 170, L.H // 2 - 50, L.W // 2 + 170, L.H // 2 + 50)
        self.round(box, 18, (8, 14, 30), 240, L.GOLD, 160)
        self.text("label", "Saved" if saved else "No changes", L.W // 2, box[1] + 50, L.GOLD if saved else L.IVORY, "m")
        self.text("small", "fireworks!" if self.demo else "back to the countdown", L.W // 2, box[1] + 78, L.DIM, "m")
        self.fx.vfx_ui_flush()
        until = self.app.now() + 0.7
        while self.app.now() < until: self.app.tick()

    # ---------------------------------------------------------------- WiFi (pages 4 and 5)
    def start_job(self, kind, fn):
        """Run fn(wpa) in the background (scans take seconds; the page keeps answering meanwhile)."""
        if self.job and self.job["thread"].is_alive(): return
        if not wifi.present(): self.wifi_msg = "No WiFi hardware (is the ESP32 connected?)"; self.draw_wifi_status(); return
        if self.wpa is None: self.wpa = wifi.connect()
        job = {"kind": kind, "result": None, "error": None}
        def work():
            try: job["result"] = fn(self.wpa)
            except (wifi.WifiError, OSError) as e: job["error"] = e
        job["thread"] = threading.Thread(target=work, daemon=True); self.job = job; job["thread"].start()

    def start_scan(self):
        if not wifi.present(): self.wifi_msg = "No WiFi hardware (is the ESP32 connected?)"; self.draw_wifi_status(); return
        self.scanning = True; self.wifi_msg = ""; self.draw_wifi_status()
        self.start_job("scan", lambda w: w.scan())

    def wifi_tick(self, now):
        """A finished background job, and what wpa_supplicant says now (once a second)."""
        job = self.job
        if job and not job["thread"].is_alive():
            self.job = None
            if job["error"] is not None:
                print("settings: wifi %s: %s" % (job["kind"], job["error"]), flush=True)
                self.wifi_msg = "WiFi isn't running yet" if "running" in str(job["error"]) else \
                                "Couldn't connect: check the password" if job["kind"] == "join" else str(job["error"])[:60]
                self.scanning = False; self.joining = None
            elif job["kind"] == "scan":
                self.scanning = False; self.nets = job["result"] or []
            elif job["kind"] == "forget":
                self.wifi_state = ("off", "")
            if self.page == 4: self.draw_page()
            else: self.fx.vfx_ui_flush()
        if now >= self.next_status and wifi.present() and not (self.job and self.job["kind"] in ("join", "forget")):
            self.next_status = now + 1.0
            try:
                if self.wpa is None: self.wpa = wifi.connect()
                state = self.wpa.status()
            except (wifi.WifiError, OSError):
                state = ("off", "")
            if self.joining:
                if state[0] == "connected": self.joining = None; self.wifi_msg = "Saved on the board"
                elif now > self.joining[1]: self.joining = None; self.wifi_msg = "Couldn't connect: check the password"
            if state != self.wifi_state or self.page == 4:
                changed = state != self.wifi_state; self.wifi_state = state
                if self.page == 4:
                    self.draw_wifi_status()
                    if changed: self.draw_wifi_buttons(); [self.draw_net_row(i) for i in range(min(len(self.nets), L.WIFI_ROWS))]

    def pick_network(self, net):
        ssid, bars, secured = net
        if not secured: self.join(ssid, None); return
        self.join_ssid = ssid; self.typed = ""; self.kb_layer = "letters"; self.kb_shift = False
        self.page = 5; self.draw_page()

    def join(self, ssid, password):
        if password is not None and len(password) < 8:            # (WPA passwords are 8 to 63 characters)
            self.flash_field(); return
        self.joining = (ssid, self.app.now() + 25); self.wifi_msg = ""
        self.start_job("join", lambda w: w.join(ssid, password))
        self.page = 4; self.draw_page()

    def wifi_status_text(self):
        state, ssid = self.wifi_state
        if not wifi.present(): return "No WiFi hardware (is the ESP32 connected?)", L.DIM
        if self.joining: return "Connecting to " + self.joining[0] + "...", L.IVORY
        if self.wifi_msg and self.wifi_msg != "Saved on the board": return self.wifi_msg, L.GOLD
        if state == "connected":
            ip = wifi.ip_address() or wifi.fake_ip()
            return "Connected to " + ssid + (" · " + ip if ip else "") + ("   (saved on the board)" if self.wifi_msg else ""), L.GOLD
        if state == "connecting": return "Connecting to " + ssid + "...", L.IVORY
        if self.scanning: return "Scanning...", L.DIM
        return "Not connected · Tap a network to join it", L.DIM

    def draw_wifi_status(self):
        if self.page != 4: return
        box = (30, L.WIFI_STATUS_Y - 22, L.W - 20, L.WIFI_STATUS_Y + 10); self.bg(box)
        t, col = self.wifi_status_text()
        self.text("small", t, 40, L.WIFI_STATUS_Y, col)
        self.draw_header()

    def fit(self, font, s, w):
        """s, shortened with "..." to fit w pixels."""
        if self.width(font, s) <= w: return s
        while s and self.width(font, s + "...") > w: s = s[:-1]
        return s + "..."

    def net_row_box(self, i):
        x0, y0, x1, y1 = L.WIFI_PANEL; top = y0 + 3 + i * L.WIFI_ROW_H
        return (x0 + 8, top, x1 - 8, top + L.WIFI_ROW_H - 2)

    def draw_net_row(self, i):
        if self.page != 4 or i >= len(self.nets) or i >= L.WIFI_ROWS: return
        ssid, bars, secured = self.nets[i]; box = self.net_row_box(i)
        self.under_panel(box)
        here = self.wifi_state[0] == "connected" and self.wifi_state[1] == ssid
        if self.pressed == ("net", i): self.round(box, 10, L.GOLD, 70)
        elif here: self.round(box, 10, L.GOLD, 34)
        self.text("label", self.fit("label", ssid, 520), box[0] + 20, box[1] + 35, L.GOLD if here else L.IVORY)
        if not secured: self.text("small", "open", box[2] - 150, box[1] + 32, L.DIM)
        for b in range(4):                                  # signal: four bars
            h = 8 + b * 6; bx = box[2] - 70 + b * 13; by = box[1] + 38
            self.round((bx, by - h, bx + 9, by), 2, L.IVORY if b < bars else (255, 255, 255), 230 if b < bars else 40)

    def draw_wifi_buttons(self):
        for b in L.WIFI_BUTTONS:
            x0, y0, x1, y1 = L.WIFI_BUTTONS[b]; self.bg((x0 - 2, y0 - 2, x1 + 2, y1 + 2)); self.draw_button(b)

    def draw_wifi_page(self):
        self.text("title", "WiFi", 36, 58, L.IVORY)
        self.panel(L.WIFI_PANEL)
        for i in range(min(len(self.nets), L.WIFI_ROWS)): self.draw_net_row(i)
        if not self.nets and not self.scanning and wifi.present():
            self.text("small", "No networks found", L.W // 2, (L.WIFI_PANEL[1] + L.WIFI_PANEL[3]) // 2, L.DIM, "m")
        self.draw_wifi_buttons()
        self.draw_wifi_status()

    def hit_wifi(self, x, y):
        if y >= 396: return "back" if x < 268 else "rescan" if x < 532 else "forget"
        x0, y0, x1, y1 = L.WIFI_PANEL
        if y0 <= y < y1:
            i = (y - y0 - 3) // L.WIFI_ROW_H
            if 0 <= i < min(len(self.nets), L.WIFI_ROWS): return ("net", i)
        return None

    # ---- page 5: the keyboard
    def layout_keys(self):
        """[(box, label, what it does)] for the keyboard's current layer."""
        rows = L.KB_LETTERS if self.kb_layer == "letters" else L.KB_SYMBOLS
        unit = (L.KB_X1 - L.KB_X0 - 9 * L.KB_GAP) / 10.0
        keys = []
        for r, row in enumerate(rows):
            w_row = sum(u * unit for _, _, u in row) + (len(row) - 1) * L.KB_GAP
            x = L.KB_X0 + (L.KB_X1 - L.KB_X0 - w_row) / 2; y = L.KB_TOP + r * (L.KB_KEY_H + L.KB_GAP)
            for label, does, u in row:
                w = u * unit
                if self.kb_shift and len(label) == 1 and label.isalpha(): label, does = label.upper(), does.upper()
                keys.append(((int(x), y, int(x + w), y + L.KB_KEY_H), label, does)); x += w + L.KB_GAP
        self.keys = keys

    def draw_key(self, i):
        box, label, does = self.keys[i]
        self.bg((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1))
        hot = self.pressed == ("key", i); on = does == "shift" and self.kb_shift
        if on: self.round(box, 9, L.GOLD, 255)
        else: self.round(box, 9, L.GOLD if hot else (255, 255, 255), 150 if hot else 30, (255, 255, 255), 70)
        cx = (box[0] + box[2]) // 2
        if len(label) == 1: self.text("label", label, cx, box[1] + 38, L.DARK if on else L.IVORY, "m")
        else: self.text("small", label, cx, box[1] + 35, L.DARK if on else L.DIM, "m")

    def draw_field(self, flash=False):
        x0, y0, x1, y1 = L.KB_FIELD
        self.bg((x0 - 1, y0 - 1, x1 + 1, y1 + 1))
        self.round(L.KB_FIELD, 12, L.PANEL_FILL, 200, L.GOLD if flash else (255, 255, 255), 200 if flash else 60)
        shown = self.typed
        while shown and self.width("label", shown) > x1 - x0 - 50: shown = shown[1:]   # (the end, if it's long)
        self.text("label", shown, x0 + 20, y0 + 40, L.IVORY)
        cx = x0 + 22 + self.width("label", shown)
        self.round((cx, y0 + 14, cx + 2, y1 - 12), 0, L.GOLD, 230)           # the caret
        if flash: self.text("small", "8 characters at least", x1 - 20, y0 + 37, L.GOLD, "r")

    def flash_field(self):
        self.draw_field(flash=True); self.fx.vfx_ui_flush()

    def draw_keyboard_page(self):
        self.text("label", self.fit("label", "Password for " + self.join_ssid, 380), 36, 50, L.IVORY)
        self.draw_field()
        self.layout_keys()
        for i in range(len(self.keys)): self.draw_key(i)
        for b in L.KB_BUTTONS: self.draw_button(b)
        self.draw_header()

    def hit_keyboard(self, x, y):
        if y >= 404: return "kb_cancel" if x < 400 else "kb_join"
        g = L.KB_GAP // 2 + 1
        for i, (box, label, does) in enumerate(self.keys):
            if box[0] - g <= x < box[2] + g and box[1] - g <= y < box[3] + g: return ("key", i)
        return None

    def type_key(self, i):
        box, label, does = self.keys[i]
        if does == "shift": self.kb_shift = not self.kb_shift; self.layout_keys(); self.draw_keyboard_keys(); return
        if does in ("symbols", "letters"): self.kb_layer = does; self.kb_shift = False; self.layout_keys(); self.draw_keyboard_keys(); return
        if does == "del": self.typed = self.typed[:-1]
        elif len(self.typed) < 63: self.typed += does
        self.draw_key(i); self.draw_field()
        if self.kb_shift and does.isalpha():                 # (shift is for one letter)
            self.kb_shift = False; self.layout_keys(); self.draw_keyboard_keys()

    def draw_keyboard_keys(self):
        x0 = L.KB_X0 - 4; self.bg((x0, L.KB_TOP - 4, L.KB_X1 + 4, L.KB_TOP + 4 * (L.KB_KEY_H + L.KB_GAP)))
        for i in range(len(self.keys)): self.draw_key(i)

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
        write_conf_value(path, "TRIP_DATE", "%04d-%02d-%02d" % (v["sy"], v["sm"], v["sd"]))
        write_conf_value(path, "FIREWORKS_MODE", self.mode)
        write_conf_value(path, "FIREWORKS_EVERY_MIN", self.rate)
        if self.theme and self.theme_opts:                         # the theme's setting (e.g. MAP_SHIP, RIDES)
            val = "|".join(sorted(self.theme_pick)) if self.theme.get("type") == "many" else next(iter(self.theme_pick), "")
            write_conf_value(path, self.theme["key"], val)
        write_conf_value(path, "FIREWORKS_SHOW_TIME", "%02d:%02d" % (v["fh"] % 12 + (12 if v["fa"] else 0), v["fm"]))
        if self.clock_changed:
            h = v["hh"] % 12 + (12 if v["ap"] else 0)
            stamp = "%04d-%02d-%02d %02d:%02d:00" % (v["ty"], v["tm"], v["td"], h, v["mi"])
            if self.app.sim: print("settings: (preview) would set the clock to", stamp, flush=True)
            else: os.system("date -s '%s' >/dev/null" % stamp); self.app.save_clock()
        print("settings: saved", flush=True)
