"""Live ride wait times for a park app's wait-times screen (board.py), from ThemeParks.wiki, into
$APP_DATA/waits.json. Part of the countdown runtime: any countdown app whose app.json has a "park"
uses it (the castle, EPCOT...).

The app's service (parks/service: S99app runs it beside the app; with no WiFi it sleeps) runs this with
--once every few minutes: the park's live data (each ride's status and standby wait, the shows'
times), and its schedule (opening hours) when the one it has is over an hour old; then it exits, so
its Python and TLS take memory only for the seconds of a fetch (the countdown and WiFi leave little).
Exit status: 0 fetched, 1 couldn't (the service waits longer each time), 2 no network time yet.
Without --once it loops by itself (for trying it on a desktop). ThemeParks.wiki's API is free and
needs no key. The park: PARK in the app's countdown.conf if set, else its app.json "park": {"id": ...}
(a ThemeParks.wiki entity id; the app's folder is the current directory), else Magic Kingdom.

waits.json, written whole each time (the screen just rereads it):
    {"park": "Magic Kingdom", "updated": unix time, "example": false,
     "hours": ["2026-11-22T09:00:00-05:00", "2026-11-22T23:00:00-05:00"],
     "rides": [{"name": ..., "status": "OPERATING" | "DOWN" | "CLOSED" | "REFURBISHMENT",
                "wait": minutes or null, "updated": unix time}, ...],
     "shows": [{"name": ..., "times": ["2026-11-22T20:00:00-05:00", ...]}, ...]}
Standard library only (urllib over TLS).
"""
import datetime, json, os, random, ssl, sys, time, urllib.request

DATA = os.environ.get("APP_DATA", "/apps/data/castle")           # (the app's own data)
OUT = os.path.join(DATA, "waits.json")
CONF_FILE = os.path.join(DATA, "countdown.conf")
API = "https://api.themeparks.wiki/v1/entity/"
MAGIC_KINGDOM = "75ea578a-adc8-4116-a54d-dccb60765ef9"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"           # Buildroot's ca-certificates
STATE = os.path.join(DATA, ".waits-state")              # between runs: {"hours", "hours_at", "said", "said_at"}
LIVE_EVERY, SCHEDULE_EVERY, LOG_EVERY = 5 * 60, 60 * 60, 60 * 60


def load_state():
    try: return json.load(open(STATE))
    except (OSError, ValueError): return {}


def save_state(state):
    os.makedirs(DATA, exist_ok=True)
    with open(STATE + ".tmp", "w") as f: json.dump(state, f)
    os.replace(STATE + ".tmp", STATE)


def log(state, text):
    """Log a line when it's news (or hourly), so a fetch every few minutes doesn't fill the SD card's log."""
    now = time.time()
    if text != state.get("said") or now - state.get("said_at", 0) >= LOG_EVERY:
        print("waits:", text, flush=True); state["said"], state["said_at"] = text, now


def read_conf():
    conf = {}
    try:
        for line in open(CONF_FILE):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    except OSError: pass
    return conf


CTX = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "licheepi-vacation-countdown"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return json.load(r)


def iso_time(text):
    """ThemeParks.wiki's times ("2026-11-23T03:52:00.123Z") as unix time; None if not that."""
    try: return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def today_hours(schedule):
    """Today's opening hours (the park's own date: from its local times), as [open, close] ISO strings."""
    days = [s for s in schedule.get("schedule", []) if s.get("type") == "OPERATING"]
    today = datetime.date.today().isoformat()
    for s in days:
        if s.get("date") == today: return [s.get("openingTime"), s.get("closingTime")]
    return None


def snapshot(park, live, hours):
    rides, shows = [], []
    for x in live.get("liveData", []):
        kind = x.get("entityType")
        if kind == "ATTRACTION":
            q = (x.get("queue") or {}).get("STANDBY") or {}
            rides.append({"name": x.get("name", ""), "status": x.get("status", ""), "wait": q.get("waitTime"),
                          "updated": iso_time(x.get("lastUpdated"))})
        elif kind == "SHOW" and x.get("showtimes"):
            shows.append({"name": x.get("name", ""), "times": [t.get("startTime") for t in x["showtimes"] if t.get("startTime")]})
    rides.sort(key=lambda r: r["name"])
    return {"park": live.get("name") or park, "updated": time.time(), "example": False, "hours": hours, "rides": rides, "shows": shows}


def write(data):
    os.makedirs(DATA, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, indent=0)
    os.replace(tmp, OUT)


def fetch_once(park, state):
    """One fetch into waits.json: 0 fetched, 1 failed, 2 no network time yet (TLS needs it)."""
    if time.time() < 1.7e9:                                        # (before 2023)
        log(state, "waiting for the clock (network time)"); return 2
    try:
        if time.time() - state.get("hours_at", 0) >= SCHEDULE_EVERY or not state.get("hours"):
            state["hours"], state["hours_at"] = today_hours(get(park + "/schedule")), time.time()
        data = snapshot(park, get(park + "/live"), state.get("hours"))
        write(data)
    except (OSError, ValueError) as e:                             # (urllib's errors are OSErrors)
        log(state, "can't fetch: %s" % e); return 1
    up = sum(1 for r in data["rides"] if r["status"] == "OPERATING")
    log(state, "%s: %d rides open of %d" % (data["park"], up, len(data["rides"])))
    return 0


def app_park():
    """The app's park id: its app.json's "park" (the service runs in the app's folder)."""
    try: return (json.load(open("app.json")).get("park") or {}).get("id")
    except (OSError, ValueError, AttributeError): return None


def main():
    park = read_conf().get("PARK") or app_park() or MAGIC_KINGDOM
    if "--once" in sys.argv[1:]:
        state = load_state()
        status = fetch_once(park, state)
        save_state(state)
        return status
    state, wait = {}, 30
    while True:
        status = fetch_once(park, state)
        if status == 0: wait = 30; time.sleep(LIVE_EVERY)
        elif status == 2: time.sleep(10)
        else: time.sleep(wait + random.uniform(0, wait / 2)); wait = min(wait * 2, 900)

if __name__ == "__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: sys.exit(0)
