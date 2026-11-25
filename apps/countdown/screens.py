"""The screen types the countdown runtime has, for any countdown app: an app's app.json "screens" lists
them, in the order they show (in turn with the countdown, each for its seconds):

    "screens": [{"type": "waits", "secs": 60},
                {"type": "weather", "place": "Yosemite Valley, California", "lat": 37.74, "lon": -119.59,
                 "units": "F", "secs": 30}]

- waits: a park's ride wait times (parks/board.py; the park: app.json "park")
- weather: the forecast for a place (weather/screen.py; its "place", "lat", "lon", "units": "F" or "C")
- ships: where the Disney ships are, by their itineraries (ships/screen.py; the app's own map imagery in
  its "map" folder, the ship to follow in its settings: MAP_SHIP)
Each type's data comes from its fetcher, run once now and then by the app's service (screens.sh: one
fetcher at a time, each as often as its type says). "secs" is seconds, or the name of a setting that
holds them; "enabled", optional, the name of a setting that's 0 to leave the screen out. (A screen of
the app's own: {"file": ..., "class": ...}, as the cruise's fleet map.)

    python3 screens.py --plan     (in an app's folder) the fetchers its screens need: "name every path" lines
"""
import json, sys

TYPES = {
    "waits":   {"file": "parks/board.py",    "class": "WaitsScreen",   "fetch": "parks/waits.py",   "every": 300},
    "weather": {"file": "weather/screen.py", "class": "WeatherScreen", "fetch": "weather/fetch.py", "every": 1800},
    "ships":   {"file": "ships/screen.py",   "class": "MapScreen",     "fetch": "ships/fetch.py",   "every": 1800},
}


def resolve(spec):
    """A screen's spec with its type's file, class and fetcher filled in (from the runtime: "from": "runtime")."""
    t = TYPES.get(spec.get("type"))
    if not t: return spec
    return dict(t, **spec, **{"from": "runtime"})


def plan(app_json="app.json"):
    """[(name, every, path)]: the fetchers an app's screens need, each once."""
    try: meta = json.load(open(app_json))
    except (OSError, ValueError): return []
    out, seen = [], set()
    for s in meta.get("screens", []):
        t = TYPES.get(s.get("type"))
        if t and t["fetch"] not in seen:
            seen.add(t["fetch"]); out.append((s["type"], t["every"], t["fetch"]))
    return out


if __name__ == "__main__" and "--plan" in sys.argv[1:]:
    for name, every, path in plan(): print(name, every, path)
