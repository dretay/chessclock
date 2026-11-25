"""The weather for a countdown app's weather screen (screen.py), from Open-Meteo (free, no key, for
non-commercial use; it asks for a credit, which the screen shows), into $APP_DATA/weather.json.

The app's service (the runtime's screens.sh) runs this with --once about every half hour; it fetches and
exits, so its Python takes memory only for the seconds of a fetch. The place: the app's app.json weather
screen ({"type": "weather", "place": ..., "lat": ..., "lon": ..., "units": "F" or "C"}; the app's folder
is the current directory). Exit status: 0 fetched, 1 couldn't (the service waits longer each time), 2 no
network time yet (TLS needs it). Without --once it loops by itself (for a desktop).

weather.json, written whole each time (the screen just rereads it):
    {"place": "Yosemite Valley, California", "units": "F", "updated": unix time, "example": false,
     "now": {"temp": 61.2, "code": 2, "wind": 6.1},
     "days": [{"date": "2026-11-25", "code": 3, "hi": 64.0, "lo": 38.5, "rain": 10, "precip": 0.0, "snow": 0.0,
               "sunrise": "2026-11-25T06:55", "sunset": "2026-11-25T16:44"}, ...]}     (10 days; "days" in the screen's
    settings for more or fewer, up to 16. rain: the chance of rain or snow, %; precip: how much, inches or mm;
    snow: how much snow, inches or cm)
codes: the WMO weather codes (0 clear ... 95 thunderstorm: screen.py has their words and pictures).
Standard library only (urllib over TLS).
"""
import json, os, ssl, sys, time, urllib.parse, urllib.request

DATA = os.environ.get("APP_DATA", ".")
OUT = os.path.join(DATA, "weather.json")
API = "https://api.open-meteo.com/v1/forecast"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"           # Buildroot's ca-certificates
CTX = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)
EVERY = 30 * 60


def place():
    """The app's weather screen's settings (app.json), or None."""
    try:
        for s in json.load(open("app.json")).get("screens", []):
            if s.get("type") == "weather" and "lat" in s and "lon" in s: return s
    except (OSError, ValueError): pass
    return None


def fetch(where):
    """The forecast for a place, as weather.json has it."""
    units = "C" if str(where.get("units", "F")).upper().startswith("C") else "F"
    q = {"latitude": where["lat"], "longitude": where["lon"], "timezone": "auto", "forecast_days": int(where.get("days", 10)),
         "current": "temperature_2m,weather_code,wind_speed_10m",
         "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,sunrise,sunset",
         "temperature_unit": "fahrenheit" if units == "F" else "celsius", "wind_speed_unit": "mph" if units == "F" else "kmh",
         "precipitation_unit": "inch" if units == "F" else "mm"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "licheepi-vacation-countdown"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r: d = json.load(r)
    cur, day = d.get("current", {}), d.get("daily", {})
    days = []
    for i, date in enumerate(day.get("time", [])):
        def v(k): return (day.get(k) or [None] * (i + 1))[i]
        snow = v("snowfall_sum")                                  # (cm, always: as inches when the units are F)
        if snow is not None and units == "F": snow = round(snow / 2.54, 1)
        days.append({"date": date, "code": v("weather_code"), "hi": v("temperature_2m_max"), "lo": v("temperature_2m_min"),
                     "rain": v("precipitation_probability_max"), "precip": v("precipitation_sum"), "snow": snow,
                     "sunrise": v("sunrise"), "sunset": v("sunset")})
    return {"place": where.get("place", ""), "units": units, "updated": time.time(), "example": False,
            "now": {"temp": cur.get("temperature_2m"), "code": cur.get("weather_code"), "wind": cur.get("wind_speed_10m")},
            "days": days}


def fetch_once():
    """One fetch into weather.json: 0 fetched, 1 failed, 2 no network time yet (TLS needs it)."""
    if time.time() < 1.7e9:
        print("weather: waiting for the clock (network time)", flush=True); return 2
    where = place()
    if not where: print("weather: no place in app.json's weather screen", flush=True); return 1
    try: data = fetch(where)
    except Exception as e:
        print("weather: couldn't fetch: %s" % e, flush=True); return 1
    os.makedirs(DATA, exist_ok=True)
    with open(OUT + ".tmp", "w") as f: json.dump(data, f)
    os.replace(OUT + ".tmp", OUT)
    d0 = data["days"][0] if data["days"] else {}
    print("weather: %s: %s°%s now, %s/%s today" % (data["place"], data["now"]["temp"], data["units"], d0.get("hi"), d0.get("lo")), flush=True)
    return 0


def main():
    if "--once" in sys.argv[1:]: return fetch_once()
    while True:
        fetch_once(); time.sleep(EVERY)


if __name__ == "__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: sys.exit(0)
