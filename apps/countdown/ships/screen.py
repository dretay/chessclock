"""The fleet map: where the Disney ships are scheduled to be, shown in turn with the countdown. Part of the
countdown runtime: the "ships" screen type (screens.py), for an app with the map's imagery in its own
"map" folder (the cruise's), its ship in its settings (MAP_SHIP, SHIP).

The Caribbean from space, NASA's Blue Marble by day and Black Marble (city lights) at night, centred on
the ship picked in Settings (MAP_SHIP): it gets a pulsing ring, its sailing so far (a line through the
ports it's called at), the way to its next port (dashed), and a card: in port until when, or at sea
bound for where, arriving when, and how far to go; its sailing. Any other ship in view is a small ship
pointing its way, with its name on a tag (your own ship, SHIP, has its name in gold on the card when
it's the one followed).

Where each ship is comes from its published itinerary, not a live report: schedule.json in the app's
data folder (/apps/data/cruise), kept up to date by schedule.py (the app's service, over WiFi): each
ship's current sailing, port by port with its times, and the route of each leg by sea. A ship is at a
port between its arrival and departure, and between two ports partway along the leg, as far as the time
since it left says. Without that file (no WiFi yet), schedule_example.json, its times moved to now.

The map comes in 256-px tiles made on a desktop (tools/themegen/build_map.py -> map/tiles/,
map.json); only the dozen or so around the ship are loaded. The cruise app's screen (its app.json).
"""
import json, math, os, time

import vacation_layout as L


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


HALO = (4, 10, 22)
FUNNEL = (200, 44, 36)                                 # Disney red
CARD_X0, CARD_X1, CARD_Y0 = 470, 788, 12          # the featured ship's card, top right


def nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def bearing(a, b):
    """Degrees from north, a to b."""
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def clock(hhmm):
    """"15:00" -> "3:00 PM" (the port's own time, as published)."""
    try: h, m = (int(v) for v in hhmm.split(":"))
    except (ValueError, AttributeError): return ""
    return "%d:%02d %s" % (h % 12 or 12, m, "PM" if h >= 12 else "AM")


def sailing_name(title):
    """CruiseMapper's "4 nights, round-trip from Fort Lauderdale, USA" -> "4 nights from Fort Lauderdale"."""
    t = title.replace(", USA", "").replace(", round-trip from ", " from ").replace("round-trip from ", "from ").strip()
    parts = t.split(" from ", 1)                                     # ("Singapore, Singapore": the city once)
    if len(parts) == 2 and "," in parts[1] and parts[1].split(",")[0].strip() == parts[1].split(",")[1].strip(): t = parts[0] + " from " + parts[1].split(",")[0]
    return t


def span(hours):
    """6 h 20 min, 40 min, 2 days 3 h."""
    mins = int(round(hours * 60))
    if mins < 60: return "%d min" % max(mins, 1)
    if mins < 48 * 60: return "%d h" % (mins // 60) + (" %d min" % (mins % 60) if mins % 60 and mins < 10 * 60 else "")
    return "%d days %d h" % (mins // 1440, mins % 1440 // 60)


def along(points, f):
    """The point a fraction f of the way along a line through points, and the index of the piece it's on."""
    lens = [nm(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])]
    goal = max(0.0, min(1.0, f)) * sum(lens)
    for i, d in enumerate(lens):
        if goal <= d or i == len(lens) - 1:
            t = goal / d if d else 0.0
            a, b = points[i], points[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), i
        goal -= d
    return tuple(points[0]), 0


class Ship:
    """A ship where its schedule puts it at `now`: lat, lon, heading, speed (knots, the leg's average), and
    what the card says (where; the sailing). trail: the way it's come this sailing; ahead: the way to its
    next port (both [(lat, lon)]); ports: the ports called at so far."""

    def __init__(self, name, entry, now):
        self.name, self.heading, self.speed = name, 0.0, 0.0
        self.trail, self.ahead, self.ports, self.next_port = [], [], [], None
        self.where, self.lines = "", []
        stops, legs = entry.get("stops") or [], entry.get("legs") or []
        title = sailing_name(entry.get("title") or "")
        later = entry.get("upcoming") or []
        if not stops:                                              # (between sailings, as far as the page says)
            raise ValueError("no sailing")
        def at(i, k):                                              # a stop's arrival/departure time, filling gaps
            st = stops[i]; v = st.get(k)
            return v if v else st.get("depart" if k == "arrive" else "arrive") or 0
        first, last = stops[0], stops[-1]
        if now < at(0, "depart"):                                  # not sailed yet: in its home port
            self.lat, self.lon = first["lat"], first["lon"]
            self.where = "At %s, sails %s%s" % (first["name"], "today " if at(0, "depart") - now < 18 * 3600 else first["day"] + " ", clock(first["depart_at"]))
            self.lines = [title] if title else []
            return
        if now >= at(len(stops) - 1, "arrive"):                    # the sailing's over: back in port
            self.lat, self.lon = last["lat"], last["lon"]
            self.ports = [(s["lat"], s["lon"]) for s in stops[:-1]]
            self.where = "At %s since %s %s" % (last["name"], last["day"], clock(last["arrive_at"]))
            if later: self.lines = ["Next: %s, %s" % (" ".join(later[0][0].split()[1:][::-1]), sailing_name(later[0][1]))]
            return
        for i in range(len(stops)):
            if at(i, "arrive") <= now < at(i, "depart"):           # in port
                st = stops[i]
                self.lat, self.lon = st["lat"], st["lon"]
                self.ports = [(s["lat"], s["lon"]) for s in stops[:i]]
                self.trail = [p for leg in legs[:i] for p in leg]
                self.where = "At %s until %s" % (st["name"], clock(st["depart_at"]))
                self.lines = [title] if title else []
                return
            if i + 1 < len(stops) and at(i, "depart") <= now < at(i + 1, "arrive"):    # at sea, between ports
                a, b = stops[i], stops[i + 1]
                route = legs[i] if i < len(legs) and len(legs[i]) >= 2 else [(a["lat"], a["lon"]), (b["lat"], b["lon"])]
                t0, t1 = at(i, "depart"), at(i + 1, "arrive")
                f = (now - t0) / max(1, t1 - t0)
                (self.lat, self.lon), k = along(route, f)
                self.heading = bearing(route[k], route[k + 1])
                length = sum(nm(p[0], p[1], q[0], q[1]) for p, q in zip(route, route[1:]))
                self.speed = length / max(0.1, (t1 - t0) / 3600)
                self.trail = [p for leg in legs[:i] for p in leg] + list(route[:k + 1])
                self.ahead = list(route[k + 1:])
                self.ports = [(s["lat"], s["lon"]) for s in stops[:i + 1]]
                self.next_port = (b["name"], b["lat"], b["lon"])
                togo = length * (1 - f)
                self.where = "At sea, bound for %s" % b["name"]
                self.lines = ["Arriving %s %s" % (b["day"], clock(b["arrive_at"])) if b.get("arrive_at") else "",
                              "%.0f nm to go" % togo if togo >= 1 else "", title]
                self.lines = [l for l in self.lines if l]
                return
        raise ValueError("no place in its schedule")


def read_schedule(path, now, example=False):
    """name -> Ship, where each is at `now` (an example's times moved to now), and when it was fetched."""
    try: data = json.load(open(path))
    except (OSError, ValueError): return {}, None
    shift = now - data.get("now", now) if example else 0
    ships, fetched = {}, []
    for name, entry in (data.get("ships") or {}).items():
        try: ships[name] = Ship(name, entry, now - shift)
        except (ValueError, KeyError, TypeError, IndexError): continue
        if entry.get("fetched"): fetched.append(entry["fetched"] + shift)
    return ships, (min(fetched) if fetched else None)


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
        # the imagery: the app's own (its "map" folder: tiles from tools/themegen/build_map.py; 7 MB, so not the runtime's)
        self.map_dir = os.environ.get("VACATION_MAP_DIR") or os.path.join(app.module.dir, "map")
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

    def fit(self, font, s, w):
        """s, shortened with "..." if it's wider than w."""
        if self.width(font, s) <= w: return s
        while s and self.width(font, s.rstrip(" ,") + "...") > w: s = s[:-1]
        return s.rstrip(" ,") + "..."

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
        """The followed ship's card: where it is by its schedule, and its sailing, as (text, colour) lines."""
        if s is None:
            return [("No sailing listed for it now", L.DIM)]
        return [(dms(s.lat, "N", "S") + "   " + dms(s.lon, "E", "W"), L.IVORY), (s.where, L.IVORY)] + [(t, L.DIM) for t in s.lines]

    def draw_card(self):
        fx = self.fx; lines = [(self.fit("small", t, CARD_X1 - CARD_X0 - 32), c) for t, c in self.card_lines(self.ships.get(self.follow))]
        w = max([self.width("label", self.follow)] + [self.width("small", t) for t, _ in lines]) + 32
        x0 = max(CARD_X0, CARD_X1 - w); y1 = CARD_Y0 + 50 + 22 * len(lines)
        self.card_box = (x0, CARD_Y0, CARD_X1, y1)
        fx.vfx_ui_round(x0, CARD_Y0, CARD_X1, y1, 12, rgb((6, 14, 30)), 225, rgb(L.GOLD), 120)
        self.text("label", self.follow, x0 + 16, CARD_Y0 + 34, L.GOLD if self.follow == self.mine else L.IVORY, halo=False)
        y = CARD_Y0 + 58
        for t, col in lines: self.text("small", t, x0 + 16, y, col, halo=False); y += 22

    def polyline(self, pts, width, color, alpha, dash=None):
        """A line through pts (screen), solid or dashed (dash: (on, off) pixels)."""
        fx = self.fx; carry = 0.0
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dist = math.hypot(bx - ax, by - ay)
            if not dash:
                fx.vfx_ui_line(int(ax * 16), int(ay * 16), int(bx * 16), int(by * 16), width, rgb(color), alpha); continue
            if dist < 0.5: continue
            ux, uy = (bx - ax) / dist, (by - ay) / dist; d = carry
            while d < dist:
                e = min(d + dash[0], dist)
                fx.vfx_ui_line(int((ax + ux * d) * 16), int((ay + uy * d) * 16), int((ax + ux * e) * 16), int((ay + uy * e) * 16), width, rgb(color), alpha)
                d += dash[0] + dash[1]
            carry = d - dist

    def draw_trail_and_route(self, s):
        """The followed ship's sailing so far (a line through where it's been, a dot at each port it's
        called at) and, at sea, the way to its next port (dashed, a ring at the port). Drawn under
        everything else."""
        fx = self.fx; x, y = self.proj(s.lat, s.lon)
        past = [self.proj(la, lo) for la, lo in s.trail] + [(x, y)]
        if len(past) > 1:
            self.polyline(past, 60, HALO, 70)
            self.polyline(past, 26, L.IVORY, 170)
        for la, lo in s.ports:
            px, py = self.proj(la, lo)
            fx.vfx_ui_line(int(px * 16), int(py * 16), int(px * 16), int(py * 16), 120, rgb(HALO), 150)
            fx.vfx_ui_line(int(px * 16), int(py * 16), int(px * 16), int(py * 16), 76, rgb(L.IVORY), 230)
        if s.next_port:
            ahead = [(x, y)] + [self.proj(la, lo) for la, lo in s.ahead]
            if math.hypot(ahead[-1][0] - x, ahead[-1][1] - y) > 30:
                # (starts clear of the ship, stops short of the port's ring)
                self.polyline(ahead, 56, HALO, 90, dash=(9, 7))
                self.polyline(ahead, 30, L.GOLD, 210, dash=(9, 7))
                tx, ty = ahead[-1]
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
        r = self.meta.get("region")
        if s and r and not (r[0] + 4 < s.lon < r[2] - 4 and r[1] + 2 < s.lat < r[3] - 2):
            self.text("small", "Beyond the Caribbean map", L.W // 2 - self.width("small", "Beyond the Caribbean map") // 2, 300, L.IVORY)
        if example: self.text("small", "Example schedules", 24, 466, L.GOLD)
        else:
            self.text("small", "Where the itineraries put them", 24, 466, L.DIM)
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
        live = os.environ.get("VACATION_SCHEDULE") or os.path.join(app.module.data_dir, "schedule.json")
        example = not os.path.exists(live)
        path = os.path.join(app.module.dir, "schedule_example.json") if example else live   # (the app's example)
        self.ships, fetched = read_schedule(path, time.time(), example)
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
            # a tap: back to the countdown; held (as on the countdown): Settings
            if hasattr(app, "screen_touch"):
                if app.screen_touch(now): break
            elif tp and any(ev == "up" for ev, x, y in tp.poll(now)): break
            self.pulse(((now - start) % 2.0) / 2.0)
            app.tick(); app.tick()                          # ~12 updates a second is plenty
        app.fade(0, lambda: self.pulse(((app.now() - start) % 2.0) / 2.0))
        fx.vfx_ui_close()
        return True
