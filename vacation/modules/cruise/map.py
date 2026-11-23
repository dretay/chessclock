"""The fleet map: where the Disney ships are, shown in turn with the countdown.

The Caribbean from space, NASA's Blue Marble by day and Black Marble (city lights) at night, centred on
the ship picked in Settings (MAP_SHIP): it gets a pulsing ring and a card with what its AIS reports
(position, speed and course, status, destination, distance and time to go, its ETA and whether it's
running early or late, and how far it's come today). Any other ship in
view is a small ship pointing its way, with its name on a tag (your own ship, SHIP, has its name in gold on the card when it's the one followed). The
status line says how old the positions are.

The map comes in 256-px tiles made on a desktop (tools/themegen/build_map.py -> map/tiles/,
map.json); only the dozen or so around the ship are loaded. The cruise module's screen (module.json).

Positions come from a file, one ship per line (see ships_example.csv):
    name, latitude, longitude, heading, speed (knots), when (unix time or YYYY-MM-DDTHH:MM),
    and optionally destination, ETA (MM-DD HH:MM, UTC as AIS sends it), status, MMSI
the module's data folder's ships.csv (/apps/data/vacation/cruise/ships.csv) when it exists (kept up to date from
AIS by ais.py, the module's service, over WiFi; or written over serial by vacation/modules/cruise/tools/send_ships.py), otherwise the example. A later line for the same ship replaces an earlier one.
"""
import calendar, datetime, json, math, os, random, time

import vacation_layout as L


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


HALO = (4, 10, 22)
FUNNEL = (200, 44, 36)                                 # Disney red
CARD_X0, CARD_X1, CARD_Y0 = 470, 788, 12          # the featured ship's card, top right
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
MONTHS = L.MONTHS


class Ship:
    def __init__(self, name, f):
        self.name = name
        self.lat, self.lon = float(f[1]), float(f[2])
        self.heading = float(f[3]) if len(f) > 3 and f[3] else 0.0
        self.speed = float(f[4]) if len(f) > 4 and f[4] else 0.0
        self.when = None
        if len(f) > 5 and f[5]:
            self.when = float(f[5]) if f[5].replace(".", "").isdigit() else time.mktime(datetime.datetime.fromisoformat(f[5]).timetuple())
        self.dest = f[6] if len(f) > 6 else ""
        self.eta = f[7] if len(f) > 7 else ""
        self.status = f[8] if len(f) > 8 else ""
        self.mmsi = f[9] if len(f) > 9 else ""
        self.trail = []                                # earlier positions: (lat, lon), oldest first


def read_ships(path):
    """name -> Ship; and whether the file says it's an example."""
    ships, example = {}, False
    try: lines = open(path).read().splitlines()
    except OSError: return ships, example
    for line in lines:
        if line.lstrip().startswith("#"):
            if "EXAMPLE" in line.upper(): example = True
            continue
        f = [v.strip() for v in line.split(",")]
        if len(f) < 3: continue
        name = f[0] if f[0].startswith("Disney ") else "Disney " + f[0]
        try: s = Ship(name, f)
        except ValueError: continue
        old = ships.get(name)
        if old and (s.when or 0) >= (old.when or 0):                      # a newer report: the old one joins the trail
            s.trail = old.trail + [(old.lat, old.lon, old.when)]
        elif old:                                                          # (an older report, out of order)
            old.trail = sorted(old.trail + [(s.lat, s.lon, s.when)], key=lambda p: p[2] or 0); continue
        ships[name] = s
    for s in ships.values():                     # the last day of it: all of it for the day's distance, 30 points to draw
        s.day = [p for p in s.trail if not (s.when and p[2] and s.when - p[2] > 24 * 3600)]
        s.trail = thin(s.day, 30)
    return ships, example


def thin(points, n):
    """At most n of the points, evenly spread, keeping the first and last."""
    if len(points) <= n: return list(points)
    return [points[round(i * (len(points) - 1) / (n - 1))] for i in range(n)]


def nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def eta_time(eta, ref):
    """An AIS ETA ("MM-DD HH:MM", UTC as AIS sends it, no year) as unix time: the year that puts it nearest ref."""
    try:
        mo, rest = eta.split("-", 1); day, hm = rest.split(); h, m = (int(v) for v in hm.split(":"))
        year = time.gmtime(ref).tm_year
        times = []
        for y in (year - 1, year, year + 1):
            try: times.append(calendar.timegm((y, int(mo), int(day), h, m, 0)))
            except ValueError: pass
        return min(times, key=lambda t: abs(t - ref)) if times else None
    except (ValueError, IndexError, AttributeError):
        return None


def span(hours):
    """6 h 20 min, 40 min, 2 days 3 h."""
    mins = int(round(hours * 60))
    if mins < 60: return "%d min" % max(mins, 1)
    if mins < 48 * 60: return "%d h" % (mins // 60) + (" %d min" % (mins % 60) if mins % 60 and mins < 10 * 60 else "")
    return "%d days %d h" % (mins // 1440, mins % 1440 // 60)


def merc(lat): return math.log(math.tan(math.pi / 4 + math.radians(max(-85.0, min(85.0, lat))) / 2))


def dms(v, pos, neg):
    """27.3 -> 27°18′N"""
    h = pos if v >= 0 else neg; v = abs(v); d = int(v); m = int(round((v - d) * 60))
    if m == 60: d, m = d + 1, 0
    return "%d°%02d′%s" % (d, m, h)


class MapScreen:
    CX, CY = 380, 250                      # where the followed ship goes (a little left of centre: the card)

    def __init__(self, app):
        self.app, self.fx = app, app.fx
        here = os.path.dirname(os.path.abspath(__file__))
        self.map_dir = os.environ.get("VACATION_MAP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "map"))
        if not os.path.isdir(self.map_dir): self.map_dir = os.path.join(here, "map")
        self.meta = json.load(open(os.path.join(self.map_dir, "map.json")))
        m = self.meta; self.T = m["tile"]; self.WW, self.WH = self.T * m["cols"], self.T * m["rows"]
        self.K = self.WW / (2 * math.pi); self.merc_top = merc(m["lat_top"])
        self.mine = app.conf.get("SHIP", "Disney Dream")
        follow = app.conf.get("MAP_SHIP") or self.mine
        self.follow = follow if follow.startswith("Disney ") else "Disney " + follow
        self.ids = {}

    # ---------------------------------------------------------------- drawing helpers (the C library's vfx_ui_*)
    def sid(self, key):
        if key not in self.ids: self.ids[key] = self.fx.vfx_ui_find(key.encode())
        return self.ids[key]

    def parts(self, font, s, x):
        k = self.sid("%s|%s" % (font, s))
        if k >= 0: return [(k, x)], self.fx.vfx_ui_metric(k, 4)
        out = []; x0 = x
        for ch in s:                                   # character by character
            kk = self.sid("%s|%s" % (font, ch))
            if kk < 0: kk = self.sid("%s|?" % font)
            out.append((kk, x)); x += self.fx.vfx_ui_metric(kk, 4)
        return out, x - x0

    def width(self, font, s): return self.parts(font, s, 0)[1]

    def text(self, font, s, x, base, color, halo=True):
        """Text (with a dark halo, so it reads over the imagery); returns its width."""
        ps, w = self.parts(font, s, x)
        if halo:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
                for k, xx in ps: self.fx.vfx_ui_text(k, xx + dx, base + dy, rgb(HALO), 150)
        for k, xx in ps: self.fx.vfx_ui_text(k, xx, base, rgb(color), 255)
        return w

    # ---------------------------------------------------------------- places
    def world(self, lat, lon): return ((lon + 180) / 360 * self.WW, (self.merc_top - merc(lat)) * self.K)

    def screen(self, wx, wy):
        """World pixels to the screen, the short way round the world."""
        x = wx - self.ox
        while x < self.CX - self.WW / 2: x += self.WW
        while x > self.CX + self.WW / 2: x -= self.WW
        return x, wy - self.oy

    def proj(self, lat, lon): return self.screen(*self.world(lat, lon))

    def near(self, lat, lon, within=700):
        best, dist = None, 1e9
        for name, la, lo in self.meta["ports"]:
            d = math.hypot((lat - la) * 111, (lon - lo) * 111 * math.cos(math.radians(lat)))   # km, roughly
            if d < dist: best, dist = name, d
        return best if best and dist < within else None

    def on_screen(self, x, y): return 6 < x < L.W - 6 and 6 < y < L.H - 26

    # ---------------------------------------------------------------- the imagery
    def load_world(self, cx, cy, layer):
        """The tiles around world point (cx, cy) into the background, that point at (CX, CY)."""
        fx, T, m = self.fx, self.T, self.meta
        self.ox = cx - self.CX; self.oy = max(0, min(self.WH - L.H, cy - self.CY))
        info = m["layers"].get(layer) or next(iter(m["layers"].values())); flat = info["flat"]
        sea = rgb(info["sea"])
        fx.vfx_ui_bg_fill(0, 0, L.W, L.H, sea)
        d = os.path.join(self.map_dir, "tiles", layer)
        try: stored = set(os.listdir(d))
        except OSError: stored = set()
        d = d.encode()
        for ty in range(int(self.oy // T), int((self.oy + L.H - 1) // T) + 1):
            if not 0 <= ty < m["rows"]: continue
            for tx in range(int(math.floor(self.ox / T)), int(math.floor((self.ox + L.W - 1) / T)) + 1):
                key = "%d_%d" % (tx % m["cols"], ty); x, y = int(round(tx * T - self.ox)), int(round(ty * T - self.oy))
                if key in flat: fx.vfx_ui_bg_fill(x, y, x + T, y + T, rgb(flat[key]))
                elif key + ".rgb.gz" in stored: fx.vfx_ui_bg_tile(d, (key + ".rgb.gz").encode(), x, y, T, T)
        fx.vfx_ui_bg_band(L.H - 64, L.H, rgb(HALO), 0, 150)          # for the status line
        self.credit = info.get("credit", "")

    # ---------------------------------------------------------------- the picture
    def draw_ship(self, x, y, heading, speed, big=False, glow=None):
        """A ship from above, pointing its way, with a faint wake when it's moving."""
        fx = self.fx; size = "l" if big else "s"; k = int(round((heading % 360) / 15)) % 24
        if speed > 0.5:
            hx, hy = math.sin(math.radians(heading)), -math.cos(math.radians(heading))
            back = (8 if big else 6) + min(26, speed * 1.2)
            fx.vfx_ui_line(int((x - hx * 6) * 16), int((y - hy * 6) * 16), int((x - hx * (6 + back)) * 16), int((y - hy * (6 + back)) * 16),
                           40 if big else 30, rgb((220, 232, 240)), 70)
        fx.vfx_ui_text(self.sid("boath|%s|%d" % (size, k)), int(x), int(y), rgb(glow or HALO), 170 if glow else 200)
        fx.vfx_ui_text(self.sid("boat|%s|%d" % (size, k)), int(x), int(y), rgb((246, 244, 238)), 255)
        fx.vfx_ui_text(self.sid("boatf|%s|%d" % (size, k)), int(x), int(y), rgb(FUNNEL), 255)

    def tag_box(self, lx, base, w): lx, base = int(lx), int(base); return (lx - 8, base - 17, lx + w + 8, base + 6)

    def place_label(self, x, y, w, taken):
        """A spot beside the ship for its name tag, where it overlaps least (a free spot if there is
        one). taken: (box, weight). Returns x, baseline, box, and whether it went further out."""
        best = None
        spots = ((16, 6), (-16 - w, 6), (-w / 2, -16), (-w / 2, 30), (14, -12), (-14 - w, -12), (14, 24), (-14 - w, 24),
                 (20, -30), (-20 - w, -30), (20, 42), (-20 - w, 42))          # in order of preference
        for i, (dx, dy) in enumerate(spots):
            lx, base = x + dx, y + dy; box = self.tag_box(lx, base, w)
            if box[0] < 4 or box[2] > L.W - 4 or box[1] < 4 or box[3] > L.H - 28: continue
            cost = i * 2
            for b, weight in taken:
                ox, oy = min(box[2], b[2]) - max(box[0], b[0]), min(box[3], b[3]) - max(box[1], b[1])
                if ox > 0 and oy > 0: cost += ox * oy * weight
            if best is None or cost < best[0]: best = (cost, int(lx), int(base), box, i >= 8)
        if best is None: lx, base = int(x + 16), int(y + 6); return lx, base, self.tag_box(lx, base, w), False
        return best[1], best[2], best[3], best[4]

    def card_lines(self, s):
        """The followed ship's AIS details, as (text, colour) lines."""
        if s is None: return [("No position reported yet", L.DIM)]
        lines = [(dms(s.lat, "N", "S") + "   " + dms(s.lon, "E", "W"), L.IVORY)]
        status = s.status.lower() if s.status else ("under way" if s.speed > 0.5 else "stopped")
        if s.speed > 0.5:
            lines.append(("%.0f kn · course %03.0f° %s" % (s.speed, s.heading % 360, COMPASS[int((s.heading % 360 + 22.5) // 45) % 8]), L.IVORY))
        place = self.near(s.lat, s.lon, 60 if status in ("moored", "at anchor", "stopped") else 700)
        if status in ("moored", "at anchor", "stopped"):
            lines.append((status.capitalize() + (" at " + place if place else ""), L.IVORY))
        else:
            lines.append(("Under way" + (", near " + place if place else ", at sea"), L.IVORY))
        if s.dest:
            dest = s.dest.title() if s.dest.isupper() else s.dest
            now = s.when or time.time()
            due = eta_time(s.eta, now)
            lines.append((("Bound for " if s.speed > 0.5 else "Destination ") + dest, L.DIM))
            # how far, and how long at this speed (straight there: a little short of the real route)
            port = self.port_named(s.dest)
            arrive = None
            if port and s.speed > 3:
                d = nm(s.lat, s.lon, port[1], port[2])
                if d > 2:
                    hours = d / s.speed; arrive = now + hours * 3600
                    lines.append(("%.0f nm to go, about %s" % (d, span(hours)), L.DIM))     # "112 nm to go, about 6 h 20 min"
            if due:
                t = time.localtime(due)                                        # (the board's own time zone)
                eta = "Due %d %s %d:%02d %s" % (t.tm_mday, MONTHS[t.tm_mon - 1], t.tm_hour % 12 or 12, t.tm_min, "PM" if t.tm_hour >= 12 else "AM")
                if arrive and due > now:                                       # early or late, at this speed
                    late = (arrive - due) / 3600
                    off = span(abs(late)) if abs(late) < 2 else "%d h" % round(abs(late))   # (whole hours from 2 h: the card is narrow)
                    eta += " · on time" if abs(late) < 0.25 else " · %s %s" % (off, "late" if late > 0 else "early")
                lines.append((eta, L.DIM))                                     # "Due 22 Nov 8:00 AM · 40 min late"
        # how far it's come since midnight (the board's), along its trail
        midnight = time.mktime(datetime.date.today().timetuple())
        today = [p for p in getattr(s, "day", []) if p[2] and p[2] >= midnight] + [(s.lat, s.lon, s.when)]
        run = sum(nm(a[0], a[1], b[0], b[1]) for a, b in zip(today, today[1:]))
        if run >= 1: lines.append(("%.0f nm today" % run, L.DIM))
        return lines                         # (how old the positions are: the status line, bottom left)

    def draw_card(self):
        fx = self.fx; lines = self.card_lines(self.ships.get(self.follow))
        w = max([self.width("label", self.follow)] + [self.width("small", t) for t, _ in lines]) + 32
        x0 = max(CARD_X0, CARD_X1 - w); y1 = CARD_Y0 + 50 + 22 * len(lines)
        self.card_box = (x0, CARD_Y0, CARD_X1, y1)
        fx.vfx_ui_round(x0, CARD_Y0, CARD_X1, y1, 12, rgb((6, 14, 30)), 225, rgb(L.GOLD), 120)
        self.text("label", self.follow, x0 + 16, CARD_Y0 + 34, L.GOLD if self.follow == self.mine else L.IVORY, halo=False)
        y = CARD_Y0 + 58
        for t, col in lines: self.text("small", t, x0 + 16, y, col, halo=False); y += 22

    def port_named(self, dest):
        """The chart's port for an AIS destination ("NASSAU", "Port Canaveral", "US PCV"...), if it knows it."""
        d = dest.lower().replace("the ", "").strip()
        for name, la, lo in self.meta["ports"]:
            n = name.lower().replace("the ", "")
            if d and (d == n or d in n or n in d): return name, la, lo
        return None

    def draw_trail_and_route(self, s):
        """Where the followed ship has been (dots fading into the past) and, under way, a dashed line
        to where it's bound. Drawn under everything else."""
        fx = self.fx; x, y = self.proj(s.lat, s.lon)
        pts = [self.proj(la, lo) for la, lo, _ in s.trail] + [(x, y)]
        n = len(pts)
        for i in range(n - 1):                                          # faint line through them
            a = 90 + 140 * (i + 1) // n
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            fx.vfx_ui_line(int(ax * 16), int(ay * 16), int(bx * 16), int(by * 16), 60, rgb(HALO), a // 3)
            fx.vfx_ui_line(int(ax * 16), int(ay * 16), int(bx * 16), int(by * 16), 26, rgb(L.IVORY), a * 3 // 4)
        for i, (px, py) in enumerate(pts[:-1]):                          # and a dot at each report
            a = 110 + 145 * (i + 1) // n
            fx.vfx_ui_line(int(px * 16), int(py * 16), int(px * 16), int(py * 16), 120, rgb(HALO), a * 2 // 3)
            fx.vfx_ui_line(int(px * 16), int(py * 16), int(px * 16), int(py * 16), 76, rgb(L.IVORY), a)
        port = self.port_named(s.dest) if s.dest and s.speed > 0.5 else None
        if port:
            tx, ty = self.proj(port[1], port[2]); dx, dy = tx - x, ty - y; dist = math.hypot(dx, dy)
            if dist > 30:
                ux, uy = dx / dist, dy / dist; d = 16.0                      # (starts clear of the ship)
                while d < dist - 8:
                    e = min(d + 9, dist - 8)
                    a0, a1 = (x + ux * d, y + uy * d), (x + ux * e, y + uy * e)
                    fx.vfx_ui_line(int(a0[0] * 16), int(a0[1] * 16), int(a1[0] * 16), int(a1[1] * 16), 56, rgb(HALO), 90)
                    fx.vfx_ui_line(int(a0[0] * 16), int(a0[1] * 16), int(a1[0] * 16), int(a1[1] * 16), 30, rgb(L.GOLD), 210)
                    d += 16
                fx.vfx_ui_ring(int(tx * 16), int(ty * 16), 7 * 16, 30, rgb(L.GOLD), 220)

    def draw(self, example, layer):
        fx = self.fx; ships = self.ships
        s = ships.get(self.follow)
        cx, cy = self.world(s.lat, s.lon) if s else self.world(26.5, -79.0)     # no position: Florida
        t0 = time.time(); self.load_world(cx, cy, layer); self.t_world = time.time() - t0
        fx.vfx_ui_bg(0, 0, L.W, L.H, 256)
        if s: self.draw_trail_and_route(s); fx.vfx_ui_bake()           # (part of the background from here on)
        self.items = []
        self.draw_card()
        taken = [(self.card_box, 50)]
        for b in self.meta.get("port_labels", []):                            # the imagery's own port names
            x0, y0 = self.screen(b[0], b[1]); taken.append(((x0, y0, x0 + b[2] - b[0], y0 + b[3] - b[1]), 3))
        here = []
        for name, sh in ships.items():
            x, y = self.proj(sh.lat, sh.lon)
            cb = self.card_box
            under_card = cb[0] - 12 < x < cb[2] + 12 and cb[1] - 12 < y < cb[3] + 12 and name != self.follow
            if self.on_screen(x, y) and not under_card:
                here.append((name, x, y, sh.heading, sh.speed)); r = 14 if name == self.follow else 10
                taken.append(((x - r, y - r, x + r, y + r), 8))
        here.sort(key=lambda h: (h[0] != self.follow, h[0] != self.mine))
        for name, x, y, heading, speed in here:
            short = name.replace("Disney ", "")
            if name == self.follow: lx = base = 0; box = (int(x) - 14, int(y) - 14, int(x) + 14, int(y) + 14); far = False   # (named on the card)
            else:
                w = self.width("ship", short); lx, base, box, far = self.place_label(x, y, w, taken); taken.append((box, 4))
            self.items.append((name, x, y, heading, speed, name == self.mine, short, lx, base, box, far))
        for it in reversed(self.items): self.draw_item(it)                   # the followed ship last, on top
        self.draw_card()
        # how old the positions are, and the imagery's credit
        whens = [sh.when for sh in ships.values() if sh.when]
        r = self.meta.get("region")
        if s and r and not (r[0] + 4 < s.lon < r[2] - 4 and r[1] + 2 < s.lat < r[3] - 2):
            self.text("small", "Beyond the Caribbean map", L.W // 2 - self.width("small", "Beyond the Caribbean map") // 2, 300, L.IVORY)
        if example: self.text("small", "Example positions", 24, 466, L.GOLD)
        elif whens:
            age = max(0, time.time() - max(whens)) / 60
            msg = "Positions just in" if age < 2 else "Positions from %d min ago" % age if age < 120 else \
                  "Positions from %d h ago" % (age / 60) if age < 48 * 60 else "Positions from %d days ago" % (age / 1440)
            self.text("small", msg, 24, 466, L.DIM)
        if self.credit:
            k = self.sid("tiny|" + self.credit)
            if k >= 0: fx.vfx_ui_text(k, L.W - 12 - fx.vfx_ui_metric(k, 4), 468, rgb((150, 156, 166)), 255)
        fx.vfx_ui_flush()

    def draw_item(self, it):
        name, x, y, heading, speed, mine, short, lx, base, box, far = it
        follow = name == self.follow
        if far:                                             # a tag placed further out: a faint line to its ship
            tx = min(max(x, box[0]), box[2]); ty = min(max(y, box[1]), box[3])
            self.fx.vfx_ui_line(int(x * 16), int(y * 16), int(tx * 16), int(ty * 16), 16, rgb(L.IVORY), 120)
        self.draw_ship(x, y, heading, speed, big=follow, glow=L.GOLD if follow else None)
        if not follow:                                      # a name tag: unlike the ports' plain names
            self.fx.vfx_ui_round(box[0], box[1], box[2], box[3], 8, rgb((6, 14, 30)), 215, rgb(L.IVORY), 90)
            self.text("ship", short, lx, base, L.IVORY, halo=False)

    def pulse(self, phase):
        """The followed ship's ring, growing and fading every two seconds."""
        it = [i for i in self.items if i[0] == self.follow]
        if not it: return                                   # no position: just the card
        it = it[0]; x, y = it[1], it[2]; R = 34
        box = (int(x - R - 2), int(y - R - 2), int(x + R + 3), int(y + R + 3))
        self.fx.vfx_ui_bg(*box, 256)
        for other in self.items:                            # anything the ring's square covers, drawn again
            b = other[9]
            if other is not it and (not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]) or abs(other[1] - x) < R + 14 and abs(other[2] - y) < R + 14):
                self.draw_item(other)
        r = 12 + 20 * phase; a = int(220 * (1 - phase) ** 1.5)
        if a > 4: self.fx.vfx_ui_ring(int(x * 16), int(y * 16), int(r * 16), 26, rgb(L.GOLD), a)
        self.draw_item(it)
        cb = self.card_box                                  # the ring never draws over the card
        if not (box[2] < cb[0] or box[0] > cb[2] or box[3] < cb[1] or box[1] > cb[3]): self.draw_card()
        self.fx.vfx_ui_flush()

    def run(self, seconds):
        """Show the map for this long, or until a tap; returns False if there's nothing to show."""
        app, fx = self.app, self.fx
        live = app.conf.get("SHIPS_FILE") or os.path.join(app.module.data_dir, "ships.csv")
        path = os.environ.get("VACATION_SHIPS") or (live if os.path.exists(live) else os.path.join(os.path.dirname(self.map_dir), "ships_example.csv"))
        if not os.path.exists(path): path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ships_example.csv")
        self.ships, example = read_ships(path)
        # NASA's Earth by day (Blue Marble) or at night (Black Marble, the city lights), with the ship picture's
        # day and night
        if fx.vfx_ui_open_blank(app.ui_dir.encode()) != 0: return False
        t0 = time.time()
        self.draw(example, "night" if app.night > 0.5 else "day")
        print("map: following %s, drawn in %.2f s (imagery %.2f s)" % (self.follow, time.time() - t0, self.t_world), flush=True)
        start = app.now(); tp = app.touch
        app.fade(256, lambda: self.pulse(((app.now() - start) % 2.0) / 2.0))      # (drawn in the dark: fade it in)
        while app.running and app.now() - start < seconds:
            now = app.now()
            if tp and any(ev == "up" for ev, x, y in tp.poll(now)): break       # a tap: back to the countdown
            self.pulse(((now - start) % 2.0) / 2.0)
            app.tick(); app.tick()                          # ~12 updates a second is plenty
        app.fade(0, lambda: self.pulse(((app.now() - start) % 2.0) / 2.0))
        fx.vfx_ui_close()
        return True
