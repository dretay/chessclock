"""Live ship positions for the fleet map, from AIS (aisstream.io), into $MODULE_DATA/ships.csv.

The cruise module's service (module.json; the app's own service starts it): beside the countdown,
not inside it, so the map just rereads the file whenever it next shows. Its folder, MODULE_DATA, is
/apps/data/vacation/cruise on the board. Needs WiFi, and an aisstream.io API key (free; sign up at
aisstream.io) in $MODULE_DATA/ais.key, on a line of its own. It waits for the key, the
network and the clock (TLS needs the right date) by itself, and reconnects when the link drops.

The ships are the Disney fleet below, by MMSI; AIS_SHIPS in vacation.conf replaces the list
(MMSI=Name pairs, comma separated). AIS here is from shore stations only: a ship far out at sea
goes quiet until it nears a coast again, and the map shows how old its position is.

Writing: a line per ship at most every TRAIL_EVERY seconds (and when its status changes), which
makes the map's trail; the file is trimmed to the last day now and then. Lines anything else wrote
(tools/send_ships.py) are kept the same way.

Standard library only: a small websocket client over ssl (no compression extension; with a
handful of ships the traffic is tiny).
"""
import base64, datetime, json, os, random, socket, ssl, struct, sys, time

APP_DATA = os.environ.get("APP_DATA", "/apps/data/vacation")
DATA = os.environ.get("MODULE_DATA") or os.path.join(APP_DATA, "cruise")
HERE = os.path.dirname(os.path.abspath(__file__))
SHIPS_FILE = os.path.join(DATA, "ships.csv")
KEY_FILE = os.path.join(DATA, "ais.key")
CONF_FILE = os.path.join(APP_DATA, "vacation.conf")        # the app's settings (AIS_SHIPS)
HOST, PATH = "stream.aisstream.io", "/v0/stream"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"           # Buildroot's ca-certificates

# MMSI -> name (Wikipedia, CruiseMapper; 2026). AIS_SHIPS in vacation.conf replaces it.
FLEET = {
    "308516000": "Disney Magic",
    "308457000": "Disney Wonder",
    "311042900": "Disney Dream",
    "311058700": "Disney Fantasy",
    "311001098": "Disney Wish",
    "311001221": "Disney Treasure",
    "311001540": "Disney Destiny",
    "311000934": "Disney Adventure",
}

TRAIL_EVERY = 10 * 60         # seconds between a ship's lines (its trail's spacing)
KEEP = 26 * 3600              # trimming keeps this much of each ship's history...
KEEP_LINES = 160              # ...and at most this many lines of it (a day at TRAIL_EVERY)
TRIM_EVERY = 3600
QUIET = 90                    # no frame for this long: ping; twice: reconnect
STATUS = {0: "under way", 1: "at anchor", 2: "not under command", 3: "restricted", 5: "moored",
          6: "aground", 7: "fishing", 8: "under way"}


def log(*a): print("ais:", *a, flush=True)


def utc_time(text):
    """aisstream's MetaData.time_utc ("2026-11-23 02:14:56.123456789 +0000 UTC") as unix time; None if it
    isn't that. The time the shore station heard the ship, so right even before the board's own clock is."""
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def read_conf():
    conf = {}
    try:
        for line in open(CONF_FILE):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    except OSError: pass
    return conf


def fleet():
    spec = read_conf().get("AIS_SHIPS", "")
    if not spec: return dict(FLEET)
    ships = {}
    for part in spec.split(","):
        if "=" in part:
            m, n = part.split("=", 1)
            if m.strip().isdigit() and n.strip(): ships[m.strip()] = n.strip()
    return ships or dict(FLEET)


def api_key():
    try:
        for line in open(KEY_FILE):
            if line.strip() and not line.startswith("#"): return line.strip()
    except OSError: pass
    return None


# ---- the websocket (RFC 6455, client side: masked frames out, text frames in) ----

class Closed(Exception): pass


class WebSocket:
    def __init__(self, host, path):
        ctx = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)
        raw = socket.create_connection((host, 443), timeout=20)
        self.s = ctx.wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(1024)
            if not chunk: raise Closed("closed during the handshake")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status + " ": raise Closed("handshake refused: " + status)

    def send(self, payload, op=1):
        if isinstance(payload, str): payload = payload.encode()
        n = len(payload)
        head = bytes([0x80 | op])
        if n < 126: head += bytes([0x80 | n])
        elif n < 65536: head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else: head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk: raise Closed("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout):
        """The next text or binary message, as bytes; None if nothing came within timeout."""
        self.s.settimeout(timeout)
        message = b""
        while True:
            try: b0, b1 = self._read(2)
            except (socket.timeout, TimeoutError):
                if message: raise Closed("stalled in the middle of a message")
                return None
            self.s.settimeout(30)                      # the rest of a frame follows quickly
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126: n = struct.unpack(">H", self._read(2))[0]
            elif n == 127: n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask: data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 8: raise Closed("closed by the server" + (": " + data[2:].decode(errors="replace") if len(data) > 2 else ""))
            if op == 9: self.send(data, op=10); continue          # ping -> pong
            if op == 10: return b""                               # a pong to our ping: the link is alive
            message += data
            if b0 & 0x80: return message                          # FIN: the message is complete

    def close(self):
        try: self.send(b"\x03\xe8", op=8)
        except OSError: pass
        try: self.s.close()
        except OSError: pass


# ---- ships.csv ----

class Ships:
    def __init__(self, names):
        self.names = names                     # MMSI -> name
        self.state = {}                        # MMSI -> what AIS last said
        self.written = {}                      # MMSI -> (time, status) of its last line
        self.trimmed = 0

    def position(self, mmsi, lat, lon, sog, cog, heading, status, when=None):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0): return
        s = self.state.setdefault(mmsi, {})
        s.update(lat=lat, lon=lon, speed=sog if sog is not None and sog < 102.3 else 0.0,
                 heading=heading if heading is not None and heading < 360 else (cog if cog is not None and cog < 360 else s.get("heading", 0.0)),
                 status=STATUS.get(status, s.get("status", "")), when=when or time.time())
        last = self.written.get(mmsi)
        if not last or s["when"] - last[0] >= TRAIL_EVERY or last[1] != s["status"]:
            self.write(mmsi)

    def static(self, mmsi, dest, eta):
        s = self.state.setdefault(mmsi, {})
        s["dest"] = " ".join((dest or "").replace(",", " ").replace("@", " ").split())
        if eta and eta.get("Month") and eta.get("Day"):        # month 0: not available; AIS ETAs are UTC
            h, m = eta.get("Hour", 24), eta.get("Minute", 60)
            s["eta"] = "%02d-%02d %02d:%02d" % (eta["Month"], eta["Day"], h if h < 24 else 0, m if m < 60 else 0)

    def write(self, mmsi):
        s = self.state[mmsi]
        line = "%s,%.5f,%.5f,%.0f,%.1f,%d,%s,%s,%s,%s\n" % (
            self.names.get(mmsi, mmsi), s["lat"], s["lon"], s["heading"], s["speed"], s["when"],
            s.get("dest", ""), s.get("eta", ""), s.get("status", ""), mmsi)
        os.makedirs(DATA, exist_ok=True)
        with open(SHIPS_FILE, "a") as f: f.write(line)
        self.written[mmsi] = (s["when"], s["status"])
        log("%s %.4f %.4f %.0fkn %s" % (self.names.get(mmsi, mmsi), s["lat"], s["lon"], s["speed"], s.get("status", "")))
        if time.time() - self.trimmed > TRIM_EVERY: self.trim()

    def trim(self):
        """Keep each ship's last day (KEEP, at most KEEP_LINES lines), and comments; atomically."""
        self.trimmed = time.time()
        try: lines = open(SHIPS_FILE).read().splitlines()
        except OSError: return
        comments, per = [], {}
        for line in lines:
            if not line.strip(): continue
            if line.lstrip().startswith("#"): comments.append(line); continue
            f = [v.strip() for v in line.split(",")]
            if len(f) < 3: continue
            when = None
            if len(f) > 5 and f[5]:
                try: when = float(f[5]) if f[5].replace(".", "").isdigit() else time.mktime(datetime.datetime.fromisoformat(f[5]).timetuple())
                except ValueError: pass
            per.setdefault(f[0], []).append((when, line))
        keep = []
        for rows in per.values():
            newest = max((w for w, _ in rows if w), default=None)
            rows = [(w, l) for w, l in rows if not (newest and w and newest - w > KEEP)]
            keep += rows[-KEEP_LINES:]
        keep.sort(key=lambda r: r[0] or 0)
        tmp = SHIPS_FILE + ".tmp"
        with open(tmp, "w") as f: f.write("".join(l + "\n" for l in comments + [l for _, l in keep]))
        os.replace(tmp, SHIPS_FILE)


# ---- the stream ----

def stream(key, ships):
    ws = WebSocket(HOST, PATH)
    try:
        # (within 3 s of connecting, or the server hangs up; the whole world, filtered to the fleet)
        ws.send(json.dumps({"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]],
                            "FiltersShipMMSI": sorted(ships.names),
                            "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
        log("connected; following %d ships" % len(ships.names))
        quiet = 0
        while True:
            msg = ws.recv(QUIET)
            if msg is None:
                quiet += 1
                if quiet >= 2: raise Closed("nothing from the server for %d s" % (QUIET * quiet))
                ws.send(b"", op=9)                                     # are you there?
                continue
            quiet = 0
            try: m = json.loads(msg)
            except ValueError: continue
            if "error" in m: raise Closed("aisstream: " + str(m["error"]))
            body = (m.get("Message") or {}).get(m.get("MessageType"), {})
            mmsi = str(body.get("UserID") or (m.get("MetaData") or {}).get("MMSI") or "")
            if mmsi not in ships.names: continue
            if m.get("MessageType") == "PositionReport":
                ships.position(mmsi, body.get("Latitude", 0.0), body.get("Longitude", 0.0), body.get("Sog"),
                               body.get("Cog"), body.get("TrueHeading"), body.get("NavigationalStatus"),
                               utc_time((m.get("MetaData") or {}).get("time_utc")))
            elif m.get("MessageType") == "ShipStaticData":
                ships.static(mmsi, body.get("Destination"), body.get("Eta"))
    finally:
        ws.close()


def main():
    ships = Ships(fleet())
    ships.trim()
    wait, said = 5, None
    while True:
        key = api_key()
        if not key:
            if said != "key": log("no API key yet: put an aisstream.io key in %s" % KEY_FILE); said = "key"
            time.sleep(30); continue
        if time.time() < 1.7e9:                                        # before 2023: no network time yet
            if said != "clock": log("waiting for the clock (network time)"); said = "clock"
            time.sleep(10); continue
        started = time.time()
        try:
            stream(key, ships)
        except (OSError, Closed, ssl.SSLError) as e:
            log("link down: %s" % e)
        said = None
        if time.time() - started > 300: wait = 5                      # it had been working: retry soon
        time.sleep(wait + random.uniform(0, wait / 2))
        wait = min(wait * 2, 600)


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(0)
