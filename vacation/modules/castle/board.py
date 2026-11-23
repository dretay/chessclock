"""The castle's wait-times board: shown in turn with the countdown (the castle module's screen).

Over the castle, blurred and dimmed (the scene's settings_bg), a panel of rides in two columns: each
one's standby wait, coloured by how long (green to 15 min, gold to 40, coral beyond), or "Down" when
it's broken down. The ones picked in Settings > Theme (RIDES in vacation.conf, names joined with |),
else every ride with a wait, longest first. Above: the park, today's hours, how old the waits are;
below: tonight's fireworks (SHOW_NAME, default Happily Ever After).

The waits come from waits.py, the module's service, in its data folder's waits.json
(/apps/data/vacation/castle/waits.json); without it (no WiFi), waits_example.json beside this file.
"""
import datetime, json, os, time

import vacation_layout as L
from vacation_text import Text, plain

HERE = os.path.dirname(os.path.abspath(__file__))
GREEN, GOLD, CORAL = (150, 205, 178), L.GOLD, (236, 132, 108)
ROWS, COL_W = 9, 380
PANEL = (20, 76, 780, 430)


def load(data_dir):
    """The latest waits.json, else the example; and whether it's the example."""
    for path in (os.path.join(data_dir, "waits.json"), os.path.join(HERE, "waits_example.json")):
        try: d = json.load(open(path)); return d, bool(d.get("example"))
        except (OSError, ValueError): pass
    return {"rides": [], "shows": []}, True


def clock(iso, minutes=True):
    """ "9 AM", "8:00 PM": an ISO time in the park's own local time."""
    try: t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError: return ""
    h = t.hour % 12 or 12; ap = "PM" if t.hour >= 12 else "AM"
    return "%d:%02d %s" % (h, t.minute, ap) if minutes or t.minute else "%d %s" % (h, ap)


def chosen(conf):
    return [n for n in conf.get("RIDES", "").split("|") if n.strip()]


def rides_to_show(data, picked, short=None):
    """[(name, wait, status)] for the board: the picked ones (any status), else all with a wait; longest first."""
    rides = data.get("rides", [])
    if picked:
        want = {plain(n) for n in picked}
        rides = [r for r in rides if plain(r["name"]) in want]
    else:
        rides = [r for r in rides if r.get("wait") is not None and r.get("status") in ("OPERATING", "DOWN")]
    def order(r):
        up = r.get("status") == "OPERATING" and r.get("wait") is not None
        return (0 if up else 1, -(r.get("wait") or 0), plain(r["name"]))
    short = {plain(k): v for k, v in (short or {}).items()}      # (module.json "short_names": the names people use)
    return [(short.get(plain(r["name"]), plain(r["name"])).strip('"'), r.get("wait"), r.get("status", "")) for r in sorted(rides, key=order)]


class WaitsScreen:
    def __init__(self, app):
        self.app, self.fx = app, app.fx
        self.t = Text(app.fx)

    def draw(self):
        app, fx, t = self.app, self.fx, self.t
        fx.vfx_ui_bg(0, 0, L.W, L.H, 256)                  # the castle, blurred and dimmed, over the whole screen
        data, example = load(app.module.data_dir)
        park = plain(data.get("park", "")).replace(" Park", "") or "Wait times"
        t.draw("label", park, 36, 52, GOLD)
        hours = data.get("hours")
        if hours and hours[0] and hours[1]:
            t.draw("small", "Open %s to %s" % (clock(hours[0], False), clock(hours[1], False)), L.W - 28, 34, L.IVORY, "r")
        if example: t.draw("small", "Example wait times", L.W - 28, 58, GOLD, "r")
        elif data.get("updated"):
            age = max(0, time.time() - data["updated"]) / 60
            msg = "Wait times just in" if age < 2 else "Wait times from %d min ago" % age if age < 120 else "Wait times from %d h ago" % (age / 60)
            t.draw("small", msg, L.W - 28, 58, L.DIM, "r")
        x0, y0, x1, y1 = PANEL
        fx.vfx_ui_round(x0, y0, x1, y1, 16, rgb(L.PANEL_FILL), L.PANEL_ALPHA, rgb((255, 255, 255)), L.PANEL_LINE_ALPHA)
        rides = rides_to_show(data, chosen(app.conf), app.module.meta.get("short_names"))
        print("board: %d rides%s" % (len(rides), " (example)" if example else ""), flush=True)
        if not any(s == "OPERATING" for _, _, s in rides) and not chosen(app.conf):
            # nothing open: the park's closed (or the data's empty)
            msg = "The park is closed" if data.get("rides") else "No wait times yet"
            t.draw("label", msg, L.W // 2, (y0 + y1) // 2 - 4, L.IVORY, "m")
            if hours and hours[0]: t.draw("small", "Opens at %s" % clock(hours[0], False), L.W // 2, (y0 + y1) // 2 + 30, L.DIM, "m")
        for i, (name, wait, status) in enumerate(rides[:2 * ROWS]):
            c, r = divmod(i, ROWS); cx = x0 + c * COL_W; y = y0 + 34 + r * 37
            if r: fx.vfx_ui_line((cx + 20) * 16, (y - 25) * 16, (cx + COL_W - 20) * 16, (y - 25) * 16, 16, rgb((60, 68, 92)), 160)
            right = cx + COL_W - 22
            if status == "OPERATING" and wait is not None:
                mw = t.width("small", "min")
                t.draw("small", "min", right, y, L.DIM, "r")
                t.draw("label", str(wait), right - mw - 8, y + 2, GREEN if wait <= 15 else GOLD if wait <= 40 else CORAL, "r")
                room = COL_W - 44 - mw - 8 - t.width("label", str(wait)) - 14
            else:
                word = {"DOWN": "Down", "CLOSED": "Closed", "REFURBISHMENT": "Refurbishing"}.get(status, "No wait")
                ww = t.draw("small", word, right, y, CORAL if status == "DOWN" else L.DIM, "r")
                room = COL_W - 44 - ww - 14
            t.draw("small", t.fit("small", name, room), cx + 24, y, L.IVORY if status == "OPERATING" else L.DIM)
        # tonight's fireworks, and the credit
        show_name = app.conf.get("SHOW_NAME", "Happily Ever After")
        for s in data.get("shows", []):
            if plain(s.get("name", "")) == show_name and s.get("times"):
                t.draw("small", "%s at %s" % (show_name, clock(s["times"][0])), 36, 460, GOLD); break
        t.draw("small", "Wait times: ThemeParks.wiki", L.W - 24, 462, L.DIM, "r")
        fx.vfx_ui_flush()

    def run(self, seconds):
        """Show the board for this long, or until a tap; returns False if it can't be shown."""
        app, fx = self.app, self.fx
        if fx.vfx_ui_open(app.ui_dir.encode(), app.theme_dir.encode()) != 0: return False
        self.draw()
        start = app.now(); tp = app.touch
        app.fade(256)                                       # (drawn in the dark: fade it in)
        while app.running and app.now() - start < seconds:
            if tp and any(ev == "up" for ev, x, y in tp.poll(app.now())): break      # a tap: back to the countdown
            app.tick(); app.tick()
        app.fade(0)
        fx.vfx_ui_close()
        return True


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]
