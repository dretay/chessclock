"""The weather: a screen any countdown app can show, in turn with the countdown (app.json "screens":
{"type": "weather", "place": ..., "lat": ..., "lon": ..., "units": "F"}). Part of the countdown runtime.

Over the scene, blurred and dimmed (its settings_bg): the place; now (a picture of the weather, the
temperature, in words, the wind, which days bring rain or snow, today's sunrise and sunset); ten days in
cards (each its picture, high and low, its rain (how likely) or snow (how much)); the trip's day, once
it's in the forecast, outlined in gold. The
pictures are drawn, not images: sun, clouds, rain, snow, fog, a storm.

The forecast comes from fetch.py (the app's service: the runtime's screens.sh), in the app's data folder's
weather.json; without it (no WiFi yet), weather_example.json in the app's folder.
"""
import datetime, json, math, os, time

import vacation_layout as L
from vacation_text import Text

GOLD, RAIN, SUN, CLOUD, DARK = L.GOLD, (120, 190, 255), (255, 206, 90), (226, 230, 236), (150, 156, 170)
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


def words(code):
    """The WMO weather code, in words."""
    c = code if isinstance(code, int) else -1
    if c in (0,): return "Clear"
    if c in (1,): return "Mostly clear"
    if c in (2,): return "Partly cloudy"
    if c in (3,): return "Cloudy"
    if c in (45, 48): return "Fog"
    if 51 <= c <= 57: return "Drizzle"
    if 61 <= c <= 67: return "Rain"
    if 71 <= c <= 77: return "Snow"
    if 80 <= c <= 82: return "Showers"
    if c in (85, 86): return "Snow showers"
    if 95 <= c <= 99: return "Thunderstorms"
    return ""


def kind(code):
    c = code if isinstance(code, int) else -1
    if c in (0, 1): return "sun"
    if c == 2: return "part"
    if c == 3: return "cloud"
    if c in (45, 48): return "fog"
    if 51 <= c <= 67 or 80 <= c <= 82: return "rain"
    if 71 <= c <= 77 or c in (85, 86): return "snow"
    if 95 <= c <= 99: return "storm"
    return "cloud"


def load(data_dir, app_dir):
    """The latest weather.json, else the app's example; and whether it's the example."""
    for path in (os.path.join(data_dir, "weather.json"), os.path.join(app_dir, "weather_example.json")):
        try: d = json.load(open(path)); return d, bool(d.get("example"))
        except (OSError, ValueError): pass
    return {"days": [], "now": {}}, True


def clock(iso):
    """"2026-11-25T16:44" -> "4:44 PM" (the place's own time, as the forecast gives it)."""
    try: t = datetime.datetime.fromisoformat(str(iso))
    except ValueError: return ""
    return "%d:%02d %s" % (t.hour % 12 or 12, t.minute, "PM" if t.hour >= 12 else "AM")


def wet(d):
    """What a day brings: "snow", "rain", or None (the chance of rain or snow 40% or more, or some forecast)."""
    snow, precip, chance, k = d.get("snow") or 0, d.get("precip") or 0, d.get("rain") or 0, kind(d.get("code"))
    if snow > 0 or (k == "snow" and chance >= 30): return "snow"
    if k in ("rain", "storm") and chance >= 30 or chance >= 40 or precip >= 0.1: return "rain"
    return None


def amount(v, units):
    """Snow as "3 in" / "8 cm"."""
    return ("%g in" % round(v, 1)) if units == "°F" else ("%d cm" % round(v))


def day_name(date, i):
    """"Wed"; from the eighth day on, "Wed 2" (ten days have two of some weekdays)."""
    return DAY_NAMES[date.weekday()] + (" %d" % date.day if i >= 7 else "")


def deg(v):
    return "–" if v is None else "%d" % round(v)


class WeatherScreen:
    def __init__(self, app):
        self.app, self.fx = app, app.fx
        self.t = Text(app.fx)
        self.spec = {}

    # ---------------------------------------------------------------- the pictures
    def disc(self, cx, cy, r, colour, alpha=255):
        self.fx.vfx_ui_round(int(cx - r), int(cy - r), int(cx + r), int(cy + r), int(r), rgb(colour), alpha, 0, 0)

    def line(self, ax, ay, bx, by, w, colour, alpha=255):
        self.fx.vfx_ui_line(int(ax * 16), int(ay * 16), int(bx * 16), int(by * 16), int(w * 16), rgb(colour), alpha)

    def sun(self, cx, cy, s):
        for k in range(8):                                   # rays
            a = k * math.pi / 4
            self.line(cx + math.cos(a) * s * 0.62, cy + math.sin(a) * s * 0.62, cx + math.cos(a) * s * 0.9, cy + math.sin(a) * s * 0.9, max(1.5, s * 0.09), SUN)
        self.disc(cx, cy, s * 0.45, SUN)

    def cloud(self, cx, cy, s, colour=CLOUD):
        """A cloud about 2s wide, its middle at (cx, cy)."""
        self.disc(cx - s * 0.45, cy + s * 0.05, s * 0.38, colour)
        self.disc(cx + s * 0.05, cy - s * 0.18, s * 0.5, colour)
        self.disc(cx + s * 0.5, cy + s * 0.08, s * 0.34, colour)
        self.fx.vfx_ui_round(int(cx - s * 0.82), int(cy + s * 0.02), int(cx + s * 0.84), int(cy + s * 0.42), int(s * 0.2), rgb(colour), 255, 0, 0)

    def picture(self, code, cx, cy, s):
        """The weather for a code, drawn about 2s across, centred on (cx, cy)."""
        k = kind(code)
        if k == "sun": self.sun(cx, cy, s)
        elif k == "part": self.sun(cx + s * 0.35, cy - s * 0.3, s * 0.75); self.cloud(cx - s * 0.1, cy + s * 0.15, s * 0.8)
        elif k == "cloud": self.cloud(cx, cy, s * 0.95)
        elif k == "fog":
            for i, w in enumerate((0.9, 0.7, 0.85)):
                y = cy - s * 0.4 + i * s * 0.4
                self.line(cx - s * w, y, cx + s * w, y, max(2, s * 0.14), CLOUD, 220)
        elif k in ("rain", "snow", "storm"):
            self.cloud(cx, cy - s * 0.25, s * 0.85, DARK if k == "storm" else CLOUD)
            if k == "rain":
                for i in (-1, 0, 1):
                    x = cx + i * s * 0.42
                    self.line(x, cy + s * 0.35, x - s * 0.15, cy + s * 0.75, max(1.5, s * 0.09), RAIN)
            elif k == "snow":
                for i in (-1, 0, 1):
                    self.disc(cx + i * s * 0.42, cy + s * 0.52 + (s * 0.12 if i == 0 else 0), max(2, s * 0.1), (240, 246, 255))
            else:
                pts = [(cx + s * 0.08, cy + s * 0.25), (cx - s * 0.18, cy + s * 0.58), (cx + s * 0.1, cy + s * 0.58), (cx - s * 0.12, cy + s * 0.92)]
                for (ax, ay), (bx, by) in zip(pts, pts[1:]): self.line(ax, ay, bx, by, max(2, s * 0.11), SUN)

    # ---------------------------------------------------------------- the screen
    def draw(self):
        app, fx, t = self.app, self.fx, self.t
        fx.vfx_ui_bg(0, 0, L.W, L.H, 256)                    # the scene, blurred and dimmed
        data, example = load(app.module.data_dir, app.module.dir)
        units = "°" + data.get("units", "F")
        place = data.get("place") or (self.spec or {}).get("place", "") or "Weather"
        t.draw("label", t.fit("label", place, 560), 36, 52, GOLD)
        if example: t.draw("small", "Example weather", L.W - 28, 52, GOLD, "r")
        elif data.get("updated"):
            mins = max(0, int((time.time() - data["updated"]) / 60))
            t.draw("small", "Updated just now" if mins < 2 else "Updated %d min ago" % mins if mins < 120 else "Updated %d h ago" % (mins // 60), L.W - 28, 52, L.DIM, "r")
        # now
        now, days = data.get("now") or {}, data.get("days") or []
        fx.vfx_ui_round(20, 72, L.W - 20, 236, 16, rgb((8, 14, 30)), 190, rgb(GOLD), 70)
        self.picture(now.get("code"), 112, 152, 52)
        x = 200
        w = t.draw("value", deg(now.get("temp")), x, 172, L.IVORY)
        t.draw("label", units, x + w + 4, 140, L.IVORY)
        t.draw("label", words(now.get("code")) or " ", 360, 138, L.IVORY)
        if now.get("wind") is not None: t.draw("small", "Wind %d %s" % (round(now["wind"]), "mph" if units == "°F" else "km/h"), 360, 172, L.DIM)
        if days:
            d0 = days[0]
            # the answer to "will it rain or snow?": which days, in the forecast's span
            def names(kind_):
                out = []
                for i, d in enumerate(days):
                    if wet(d) != kind_: continue
                    try: out.append("today" if i == 0 else day_name(datetime.date.fromisoformat(d["date"]), i))
                    except (KeyError, ValueError): pass
                return out if len(out) <= 3 else out[:3] + ["+%d" % (len(out) - 3)]
            r, sn = names("rain"), names("snow")
            if r or sn:
                line = " · ".join(p for p in ("Rain: " + ", ".join(r) if r else "", "Snow: " + ", ".join(sn) if sn else "") if p)
                t.draw("small", t.fit("small", line, L.W - 380), 360, 200, GOLD)
            else:
                t.draw("small", "No rain or snow in the next %d days" % len(days), 360, 200, L.DIM)
            if d0.get("sunrise") and d0.get("sunset"):
                t.draw("small", "Sunrise %s · sunset %s" % (clock(d0["sunrise"]), clock(d0["sunset"])), 360, 224, L.DIM)
        # the days
        trip = getattr(app, "sail", None)
        shown = days[:10]
        if shown:
            gap = 6 if len(shown) > 7 else 8; cw = (L.W - 40 - gap * (len(shown) - 1)) // len(shown)
            s_pic = 20 if len(shown) > 7 else 24
            for i, d in enumerate(shown):
                x0 = 20 + i * (cw + gap); x1 = x0 + cw; cx = (x0 + x1) // 2
                try: date = datetime.date.fromisoformat(d["date"])
                except (KeyError, ValueError): date = None
                is_trip = bool(trip and date and date == trip)
                fx.vfx_ui_round(x0, 250, x1, 458, 12, rgb((8, 14, 30)), 190, rgb(GOLD), 255 if is_trip else 50)
                name = "Today" if i == 0 else day_name(date, i) if date else ""
                t.draw("small", name, cx, 278, GOLD if is_trip else L.IVORY, "m")
                if is_trip: t.draw("small", "Trip day", cx, 298, GOLD, "m")
                self.picture(d.get("code"), cx, 334, s_pic)
                t.draw("label", deg(d.get("hi")) + "°", cx, 390, L.IVORY, "m")
                t.draw("small", deg(d.get("lo")) + "°", cx, 412, L.DIM, "m")
                w_ = wet(d)                                          # (rain or snow, said: how likely, how much snow)
                if w_ == "snow":
                    t.draw("small", "Snow", cx, 432, (240, 246, 255), "m")
                    if d.get("snow"): t.draw("small", amount(d["snow"], units), cx, 448, (240, 246, 255), "m")
                elif w_ == "rain" or (d.get("rain") or 0) >= 20:
                    t.draw("small", "Rain", cx, 432, RAIN, "m"); t.draw("small", "%d%%" % (d.get("rain") or 0), cx, 448, RAIN, "m")
        else:
            t.draw("label", "No forecast yet", L.W // 2, 340, L.DIM, "m")
        t.draw("small", "Weather: Open-Meteo", L.W - 24, 476, L.DIM, "r")
        fx.vfx_ui_flush()

    def run(self, seconds):
        """Show the weather for this long, or until a tap; returns False if it can't be shown."""
        app, fx = self.app, self.fx
        if fx.vfx_ui_open(app.ui_dir.encode(), app.theme_dir.encode()) != 0: return False
        self.draw()
        start = app.now(); tp = app.touch
        app.fade(256)                                       # (drawn in the dark: fade it in)
        while app.running and app.now() - start < seconds:
            # a tap: on to the next screen, or back to the countdown; held (as on the countdown): Settings
            if hasattr(app, "screen_touch"):
                if app.screen_touch(app.now()): break
            elif tp and any(ev == "up" for ev, x, y in tp.poll(app.now())): break
            app.tick(); app.tick()
        app.fade(0)
        fx.vfx_ui_close()
        return True
