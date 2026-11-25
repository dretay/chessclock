"""Where the Disney ships are scheduled to be: each ship's current sailing, port by port with its times,
into $APP_DATA/schedule.json for the fleet map (map.py), which places each ship from it: at a port
between its arrival and departure, or partway along the leg between two ports.

The cruise app's service (S99app runs it beside the app; with no WiFi it sleeps) runs this with --once
every half hour; it fetches only the ships that are due: each about every 12 hours, and soon after its
sailing ends (for the next one). The schedules come from CruiseMapper's ship pages (the current sailing's
table: ports, with local arrival and departure times), one page every few seconds; each port's place from
its page there, once (kept in ports.json). Each leg's route through the water (around Florida rather than
across it), worked out from map/sea.bin (tools/themegen/build_sea.py), once per pair of ports (routes.json).

Exit status: 0 fetched (or nothing due), 1 couldn't (the service waits longer each time), 2 no network
time yet (TLS needs it). Without --once it loops by itself (for a desktop). SCHEDULE_SHIPS: just these
(comma-separated names). The CruiseMapper page layout is what it reads: if they change it, this says so
in the log ("couldn't read") and the map keeps the last schedule.
"""
import calendar, datetime, heapq, json, math, os, re, ssl, sys, time, urllib.request
from array import array

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("APP_DATA", "/apps/data/cruise")
OUT = os.path.join(DATA, "schedule.json")
PORTS_FILE = os.path.join(DATA, "ports.json")          # CruiseMapper's port id -> [name, lat, lon]
ROUTES_FILE = os.path.join(DATA, "routes.json")        # "from>to" -> [[lat, lon], ...]
SEA_FILE = os.path.join(HERE, "map", "sea.bin")
SITE = "https://www.cruisemapper.com"
SHIPS = {"Disney Magic": "Disney-Magic-684", "Disney Wonder": "Disney-Wonder-692",
         "Disney Dream": "Disney-Dream-548", "Disney Fantasy": "Disney-Fantasy-649",
         "Disney Wish": "Disney-Wish-2127", "Disney Treasure": "Disney-Treasure-2128",
         "Disney Destiny": "Disney-Destiny-2129", "Disney Adventure": "Disney-Adventure-2103"}
UA = "Mozilla/5.0 (compatible; countdown-clock/1.0)"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"           # Buildroot's ca-certificates
CTX = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)
EVERY, AFTER_END, PAUSE = 12 * 3600, 3600, 4             # a ship's schedule: how often, after its sailing ends; between pages
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def say(text): print("schedule:", text, flush=True)


def load(path, default):
    try: return json.load(open(path))
    except (OSError, ValueError): return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f: json.dump(obj, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def get(path):
    req = urllib.request.Request(SITE + path, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r: return r.read().decode("utf-8", "replace")


def text(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", h)).replace("&amp;", "&").strip()


# ------------------------------------------------------------------------------------------- local times
def nth_sunday(y, m, n):
    first = 1 + (6 - datetime.date(y, m, 1).weekday()) % 7
    return first + 7 * (n - 1)


def last_sunday(y, m):
    last = (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1))
    return last.day - (last.weekday() + 1) % 7


def zone(cc, lat, lon):
    """A port's standard UTC offset (hours) and its summer-time rule, from its country and place."""
    if cc == "us":
        if lon > -68: return -4, None                                 # (Puerto Rico, the USVI)
        for edge, off in ((-87.6, -5), (-104, -6), (-114.8, -7), (-130, -8), (-150, -9)):
            if lon >= edge: return off, "us"
        return -10, None                                              # Hawaii
    if cc == "ca":
        for edge, off in ((-68, -4), (-90, -5), (-102, -6), (-120, -7)):
            if lon >= edge: return off, "us"
        return -8, "us"
    if cc == "mx":
        for edge, off in ((-88.2, -5), (-105.5, -6), (-114, -7)):
            if lon > edge: return off, None
        return -8, "us"                                               # (Ensenada)
    if cc in ("bs", "tc", "ht", "cu"): return -5, "us"
    if cc in ("ky", "jm", "pa", "co", "ec", "pe"): return -5, None
    if cc in ("bm",): return -4, "us"
    if cc in ("hn", "bz", "gt", "sv", "ni", "cr"): return -6, None
    if cc in ("pr", "vi", "vg", "ag", "kn", "lc", "bb", "dm", "gd", "vc", "aw", "cw", "sx", "bq", "mf", "bl", "ai",
              "ms", "gp", "mq", "do", "tt", "ve"): return -4, None
    if cc in ("gb", "ie", "pt", "fo"): return 0, "eu"
    if cc == "es": return (0, "eu") if lon < -10 else (1, "eu")    # (the Canaries)
    if cc in ("is",): return 0, None
    if cc in ("fr", "it", "de", "nl", "be", "no", "dk", "se", "mt", "hr", "me", "mc", "gi", "at", "ch", "pl", "si", "al"): return 1, "eu"
    if cc in ("gr", "fi", "ee", "lv", "lt", "cy"): return 2, "eu"
    if cc == "tr": return 3, None
    if cc in ("sg", "my", "ph", "cn", "hk", "tw", "bn"): return 8, None
    if cc in ("jp", "kr"): return 9, None
    if cc == "au":
        if lon < 129: return 8, None
        if lon < 141: return 9.5, "au"
        return (10, "au") if lat < -28.5 else (10, None)
    if cc == "nz": return 12, "nz"
    return round(lon / 15), None


def to_utc(y, mo, d, hh, mm, cc, lat, lon):
    """A port's local time as unix time."""
    off, rule = zone(cc, lat, lon)
    summer = False
    if rule == "us": summer = (mo, d, hh) >= (3, nth_sunday(y, 3, 2), 2) and (mo, d, hh) < (11, nth_sunday(y, 11, 1), 2)
    elif rule == "eu": summer = (mo, d) >= (3, last_sunday(y, 3)) and (mo, d) < (10, last_sunday(y, 10))
    elif rule == "au": summer = (mo, d) >= (10, nth_sunday(y, 10, 1)) or (mo, d) < (4, nth_sunday(y, 4, 1))
    elif rule == "nz": summer = (mo, d) >= (9, last_sunday(y, 9)) or (mo, d) < (4, nth_sunday(y, 4, 1))
    return calendar.timegm((y, mo, d, hh, mm, 0)) - (off + summer) * 3600


# ------------------------------------------------------------------------------------------- the page
def parse(page):
    """A ship page: its current sailing ({"title", "stops": [{port id, name, cc, day, month, times}], "year"})
    or None, and its next sailings [(YYYY Mon DD, title)]."""
    upcoming = [(text(a), text(b)) for a, b in re.findall(
        r'<td class="cruiseDatetime">(.*?)</td>\s*<td class="cruiseTitle">(.*?)</td>', page, re.S)]
    i = page.find("cruiseItinerariesCurrent")
    if i < 0: return None, upcoming
    head = text(page[max(0, i - 3000):i])
    title = re.search(r"current cruise is \S+ (.+?)\. Prices", head) or re.search(r"current cruise is \S+ (.+?)\. The itinerary", head)
    begins = re.search(r"begins on (\w+) (\d+), (\d{4})", head)
    table = page[i:page.find("</table>", i)]
    stops = []
    for date, cell in re.findall(r'<td class="date">(.*?)</td>\s*<td class="text">(.*?)</td>', table, re.S):
        m = re.match(r"(\d+) (\w{3})\w*(?: (\d+):(\d+))?(?: - (\d+):(\d+))?", text(date))
        port = re.search(r'/ports/([^"?#]+)"[^>]*>([^<]+)</a>', cell)
        if not m or not port: continue                                  # (a day at sea, or something new)
        cc = re.search(r"flag-icon-(\w+)", cell)
        t = [int(v) if v else None for v in m.groups()[2:]]
        kind = "depart" if "Departing" in cell else "arrive" if "Arriving" in cell else "call"
        a = (t[0], t[1]) if kind != "depart" and t[0] is not None else None
        dp = (t[2], t[3]) if t[2] is not None else (t[0], t[1]) if kind == "depart" and t[0] is not None else None
        stops.append({"id": port.group(1), "full": text(port.group(2)), "cc": cc.group(1) if cc else "",
                      "day": int(m.group(1)), "month": MONTHS.get(m.group(2).lower()[:3], 0), "arrive": a, "depart": dp})
    if not stops or not begins: return None, upcoming
    year = int(begins.group(3)); start_month = MONTHS.get(begins.group(1).lower()[:3], stops[0]["month"])
    return {"title": title.group(1) if title else "", "year": year, "start_month": start_month, "stops": stops}, upcoming


def port_place(pid, ports):
    """[name, lat, lon] of a CruiseMapper port (its page, once; then ports.json)."""
    if pid not in ports:
        page = get("/ports/" + pid)
        m = re.search(r'"latitude":\s*(-?\d+\.\d+),\s*"longitude":\s*(-?\d+\.\d+)', page)
        if not m: raise ValueError("no place on the page of port " + pid)
        name = re.search(r'"ss":\s*"([^"]*)"', page)
        ports[pid] = [name.group(1) if name else pid, float(m.group(1)), float(m.group(2))]
        save(PORTS_FILE, ports); time.sleep(PAUSE)
    return ports[pid]


# ------------------------------------------------------------------------------------------- the way by sea
class Sea:
    def __init__(self, path=SEA_FILE):
        with open(path, "rb") as f:
            h = f.readline().split()
            self.lon0, self.lat0, self.step = float(h[1]), float(h[2]), float(h[3]); self.cols, self.rows = int(h[4]), int(h[5])
            self.bits = f.read()
        self.rb = (self.cols + 7) // 8

    def cell(self, lat, lon): return int((lon - self.lon0) / self.step), int((lat - self.lat0) / self.step)
    def inside(self, x, y): return 0 <= x < self.cols and 0 <= y < self.rows
    def sea(self, x, y): return self.inside(x, y) and self.bits[y * self.rb + (x >> 3)] >> (7 - (x & 7)) & 1
    def centre(self, x, y): return self.lat0 + (y + 0.5) * self.step, self.lon0 + (x + 0.5) * self.step

    def nearest_sea(self, x, y, toward, reach=24):
        """The sea nearest a port's cell; of those about as near (a harbour between islands has sea on
        both sides), the one facing `toward` (the other end of the leg)."""
        for r in range(reach + 1):
            ring = [(x + dx, y + dy) for dx in range(-r, r + 1) for dy in (-r, r)] + [(x + dx, y + dy) for dy in range(-r + 1, r) for dx in (-r, r)]
            if any(self.sea(*c) for c in ring):
                near = [(x + dx, y + dy) for dx in range(-r - 2, r + 3) for dy in range(-r - 2, r + 3)
                        if self.sea(x + dx, y + dy) and dx * dx + dy * dy <= (r + 1.5) ** 2]
                return min(near, key=lambda c: math.hypot(c[0] - x, c[1] - y) + 0.15 * math.hypot(c[0] - toward[0], c[1] - toward[1]))
        return None

    def clear(self, a, b):
        """A straight line between two cells all at sea?"""
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2) + 1
        return all(self.sea(int(a[0] + (b[0] - a[0]) * i / n + 0.5), int(a[1] + (b[1] - a[1]) * i / n + 0.5)) for i in range(n + 1))

    def route(self, a, b):
        """[(lat, lon), ...] from a to b by sea; straight when either end is outside the grid, or no way is found."""
        ca, cb = self.cell(*a), self.cell(*b)
        if not (self.inside(*ca) and self.inside(*cb)): return [a, b]
        sa, sb = self.nearest_sea(*ca, cb), self.nearest_sea(*cb, ca)
        if not sa or not sb: return [a, b]
        C, N = self.cols, self.cols * self.rows
        g = array("f", [1e30]) * N; came = array("i", [-1]) * N; done = bytearray(N)
        coslat = [math.cos(math.radians(self.lat0 + (y + 0.5) * self.step)) for y in range(self.rows)]
        def h(x, y): return math.hypot((x - sb[0]) * coslat[y], y - sb[1])
        start, goal = sa[1] * C + sa[0], sb[1] * C + sb[0]
        g[start] = 0; heap = [(h(*sa), start)]
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
        while heap:
            _, k = heapq.heappop(heap)
            if done[k]: continue
            if k == goal: break
            done[k] = 1; x, y = k % C, k // C; gk = g[k]
            for dx, dy in steps:
                nx, ny = x + dx, y + dy
                if not self.sea(nx, ny): continue
                nk = ny * C + nx
                if done[nk]: continue
                ng = gk + math.hypot(dx * coslat[y], dy)
                if ng < g[nk]: g[nk] = ng; came[nk] = k; heapq.heappush(heap, (ng + h(nx, ny), nk))
        if came[goal] < 0 and goal != start: return [a, b]
        path = [goal]
        while path[-1] != start: path.append(came[path[-1]])
        cells = [(k % C, k // C) for k in reversed(path)]
        keep = [cells[0]]                                               # the corners only: straight wherever it's clear
        i = 0
        while i < len(cells) - 1:
            j = len(cells) - 1
            while j > i + 1 and not self.clear(cells[i], cells[j]): j -= 1
            keep.append(cells[j]); i = j
        pts = [a] + [tuple(round(v, 3) for v in self.centre(*c)) for c in keep[1:-1]] + [b]
        return pts


# ------------------------------------------------------------------------------------------- one ship
def sailing(name, ports, routes, sea):
    """The ship's page into its entry in schedule.json (None if there's no current sailing on it)."""
    cur, upcoming = parse(get("/ships/%s?tab=itinerary" % SHIPS[name]))
    if cur is None:
        if not upcoming: raise ValueError("couldn't read the page for " + name)
        return {"stops": [], "legs": [], "upcoming": upcoming[:3]}
    stops = []
    for s in cur["stops"]:
        place = port_place(s["id"], ports)
        y = cur["year"] + (1 if s["month"] < cur["start_month"] else 0)
        def utc(t): return to_utc(y, s["month"], s["day"], t[0], t[1], s["cc"], place[1], place[2]) if t else None
        stops.append({"id": s["id"], "name": s["full"].split(",")[0].strip(), "full": s["full"], "lat": place[1], "lon": place[2],
                      "day": "%d %s" % (s["day"], "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[s["month"] - 1]),
                      "arrive": utc(s["arrive"]), "depart": utc(s["depart"]),
                      "arrive_at": "%02d:%02d" % s["arrive"] if s["arrive"] else "", "depart_at": "%02d:%02d" % s["depart"] if s["depart"] else ""})
    legs = []
    for a, b in zip(stops, stops[1:]):
        key = a["id"] + ">" + b["id"]
        if key not in routes:
            routes[key] = sea.route((a["lat"], a["lon"]), (b["lat"], b["lon"])) if sea else [(a["lat"], a["lon"]), (b["lat"], b["lon"])]
            save(ROUTES_FILE, routes)
        legs.append(routes[key])
    end = stops[-1]["arrive"] or stops[-1]["depart"] or 0
    later = [u for u in upcoming if u[0] and parse_day(u[0]) and parse_day(u[0]) >= end - 86400]
    return {"title": cur["title"].strip(), "stops": stops, "legs": legs, "upcoming": later[:3]}


def parse_day(s):
    """"2026 Nov 27" -> unix time (noon UTC that day), or None."""
    m = re.match(r"(\d{4}) (\w{3}) (\d+)", s)
    try: return calendar.timegm((int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)), 12, 0, 0)) if m else None
    except KeyError: return None


def due(entry, now):
    if not entry: return True
    if now - entry.get("fetched", 0) >= EVERY: return True
    stops = entry.get("stops") or []
    end = stops and (stops[-1].get("arrive") or stops[-1].get("depart"))
    return bool(end and now > end and now - entry.get("fetched", 0) >= AFTER_END)    # (its next sailing)


def fetch_once():
    """The ships that are due, into schedule.json: 0 done (or none due), 1 failed, 2 no network time yet."""
    now = time.time()
    if now < 1.7e9:
        say("waiting for the clock (network time)"); return 2
    out = load(OUT, {}); ships = out.setdefault("ships", {})
    ports, routes = load(PORTS_FILE, {}), load(ROUTES_FILE, {})
    try: sea = Sea()
    except (OSError, ValueError, IndexError): sea = None
    only = [n.strip() for n in os.environ.get("SCHEDULE_SHIPS", "").split(",") if n.strip()]
    names = [n for n in SHIPS if (not only or n in only) and due(ships.get(n), now)]
    failed = 0
    for n, name in enumerate(names):
        if n: time.sleep(PAUSE)
        try:
            entry = sailing(name, ports, routes, sea); entry["fetched"] = time.time()
            ships[name] = entry
            s = entry["stops"]
            say("%s: %s" % (name, "%s, %d stops, %s to %s" % (entry["title"] or "a sailing", len(s), s[0]["name"], s[-1]["name"]) if s else "no sailing now"))
        except Exception as e:                                           # (any one ship: the others still get theirs)
            failed += 1; say("%s: couldn't read its schedule: %s" % (name, e))
        out["updated"] = time.time(); save(OUT, out)
    return 1 if failed and failed == len(names) else 0


def main():
    if "--once" in sys.argv[1:]: sys.exit(fetch_once())
    wait = 60
    while True:
        status = fetch_once()
        if status == 0: wait = 60; time.sleep(1800)
        elif status == 2: time.sleep(10)
        else: time.sleep(wait); wait = min(wait * 2, 900)


if __name__ == "__main__":
    main()
