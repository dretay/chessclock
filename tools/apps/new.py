#!/usr/bin/env python3
"""Start a new countdown app: a folder in apps/ that runs at once (in the previewer, or deployed),
with a placeholder scene to replace with real art.

    python3 tools/apps/new.py ID --name NAME [--park PARK] [--show SHOW] [--greeting TEXT] [--date-label TEXT]

e.g.  python3 tools/apps/new.py epcot --name EPCOT --park EPCOT --show "Luminous The Symphony of Us"

--park: a theme park (its ThemeParks.wiki name, or part of it, or its entity id): the app then shows that
park's ride wait times (the countdown runtime's shared board and fetcher, parks/), with an example
of them fetched now for when there's no WiFi. Without it, just the countdown.

Writes apps/ID/: app.json, defaults.conf, run, service (with --park), splash.sh, waits_example.json
(with --park), scenes/ID/ (the placeholder: a plain sky by day, dusk and night, packed by
tools/themegen/scene_pack.py from tools/themegen/work/ID/, which is where real pictures go: day.png,
dusk.png, night.png, mask.png, windows.png, scene.json; pack them again to see them), the app's icon
and boot splash (tools/themegen/app_icon.py, app_splash.py). Refuses an ID that exists.
"""
import argparse, json, os, shutil, subprocess, sys, urllib.request

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS = os.path.join(REPO, "apps")
THEMEGEN = os.path.join(REPO, "tools", "themegen")
API = "https://api.themeparks.wiki/v1/"
UA = {"User-Agent": "licheepi-vacation-countdown"}


def get(path):
    with urllib.request.urlopen(urllib.request.Request(API + path, headers=UA), timeout=30) as r: return json.load(r)


def find_park(text):
    """(id, name) of a park by its id, name, or part of its name."""
    parks = [(p["id"], p["name"]) for d in get("destinations")["destinations"] for p in d["parks"]]
    for pid, name in parks:
        if text == pid or text.lower() == name.lower(): return pid, name
    hits = [(pid, name) for pid, name in parks if text.lower() in name.lower()]
    if len(hits) == 1: return hits[0]
    sys.exit("new: %s park matches %r%s" % ("more than one" if hits else "no", text,
             ": " + ", ".join(n for _, n in hits) if hits else " (see https://api.themeparks.wiki/v1/destinations)"))


def placeholder(work):
    """A plain sky by day, dusk and night above dark ground: something to run with until there's art."""
    from PIL import Image
    W, H, horizon = 800, 480, 400
    skies = {"day": ((96, 150, 212), (196, 220, 240), (70, 92, 72)),
             "dusk": ((44, 48, 104), (238, 150, 110), (40, 40, 52)),
             "night": ((6, 10, 26), (24, 34, 66), (12, 14, 20))}
    os.makedirs(work, exist_ok=True)
    for k, (top, low, ground) in skies.items():
        im = Image.new("RGB", (W, H)); px = im.load()
        for y in range(H):
            if y < horizon:
                t = (y / horizon) ** 1.6; c = tuple(int(a + (b - a) * t) for a, b in zip(top, low))
            else: c = ground
            for x in range(W): px[x, y] = c
        im.save(os.path.join(work, k + ".png"))
    json.dump({"horizon": horizon}, open(os.path.join(work, "scene.json"), "w"), indent=1)


def example_waits(park_id, name):
    """waits_example.json: the park's waits right now (the runtime's fetcher), marked an example."""
    sys.path.insert(0, os.path.join(APPS, "countdown", "parks"))
    import waits
    try: hours = waits.today_hours(waits.get(park_id + "/schedule"))
    except Exception: hours = None
    data = waits.snapshot(name, waits.get(park_id + "/live"), hours)
    data["example"] = True
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id"); ap.add_argument("--name", required=True)
    ap.add_argument("--park"); ap.add_argument("--show", default="")
    ap.add_argument("--greeting", default="Have a magical day!")
    ap.add_argument("--date-label", default="Park day")
    a = ap.parse_args()
    if not a.id.replace("-", "").isalnum() or a.id != a.id.lower(): sys.exit("new: an id is lower-case letters, digits and -")
    if a.id in ("data", "current", "swapfile", "system", "countdown"): sys.exit("new: %s is reserved" % a.id)
    d = os.path.join(APPS, a.id)
    if os.path.exists(d): sys.exit("new: %s exists" % os.path.relpath(d, REPO))
    park = find_park(a.park) if a.park else None

    meta = {"id": a.id, "name": a.name, "version": "0.1.0", "runtime": "countdown", "api": 3 if park else 2}
    if park: meta["park"] = {"id": park[0], "show": a.show}
    meta["exclude"] = ["scenes/*/preview.png", "splash/preview.png"]
    meta["scene"] = {"engine": "scene", "dir": "scenes", "default": a.id}
    if park:
        meta["screens"] = [{"id": "waits", "from": "runtime", "file": "parks/board.py", "class": "WaitsScreen", "enabled": "WAITS", "secs": "WAITS_SECS"}]
        meta["settings"] = [{"key": "RIDES", "label": "Rides", "note": "on the wait times (none picked: all of them)", "type": "many", "options_from": "waits.json"}]
        meta["short_names"] = {}
    meta["countdown"] = {"date_label": a.date_label, "after": "Already there", "time": "09:00"}

    os.makedirs(d)
    with open(os.path.join(d, "app.json"), "w") as f: json.dump(meta, f, indent=2); f.write("\n")
    conf = ["# %s's own settings (the first time; then its countdown.conf in /apps/data/%s)" % (a.name, a.id)]
    if park:
        conf += ["# the wait-times board, shown in turn with the countdown: 1 on, 0 off; how long it shows (seconds)",
                 "WAITS=1", "WAITS_SECS=60",
                 "# the rides it shows (Settings > Theme picks them; names joined with |): empty for all of them",
                 "RIDES=",
                 "# tonight's show the board names, and the park (a ThemeParks.wiki entity id), if not app.json's \"park\"",
                 "SHOW_NAME=", "PARK="]
    open(os.path.join(d, "defaults.conf"), "w").write("\n".join(conf) + "\n")
    shutil.copy(os.path.join(APPS, "castle", "run"), os.path.join(d, "run"))
    shutil.copy(os.path.join(APPS, "castle", "splash.sh"), os.path.join(d, "splash.sh"))
    if park:
        open(os.path.join(d, "service"), "w").write("#!/bin/sh\n# %s's background job: its park's ride wait times (the countdown runtime's, shared by the\n"
                                                    "# park apps: ../countdown/parks/service; the park is app.json's \"park\").\n"
                                                    "exec ../countdown/parks/service\n" % a.name)
        os.chmod(os.path.join(d, "service"), 0o755)
        with open(os.path.join(d, "waits_example.json"), "w") as f: json.dump(example_waits(*park), f, indent=1)
    for n in ("run", "splash.sh"): os.chmod(os.path.join(d, n), 0o755)

    work = os.path.join(THEMEGEN, "work", a.id)
    if not os.path.exists(os.path.join(work, "day.png")): placeholder(work)
    sc = json.load(open(os.path.join(work, "scene.json"))); sc.setdefault("greeting", a.greeting)
    json.dump(sc, open(os.path.join(work, "scene.json"), "w"), indent=1)
    py = sys.executable
    for cmd in ([py, os.path.join(THEMEGEN, "scene_pack.py"), work, os.path.join(d, "scenes", a.id)],
                [py, os.path.join(THEMEGEN, "app_icon.py"), a.id], [py, os.path.join(THEMEGEN, "app_splash.py"), a.id]):
        subprocess.run(cmd, check=True)
    print("new: %s (%s)%s. Try it: python3 tools/preview/preview.py %s" % (
        os.path.relpath(d, REPO), a.name, ", wait times for %s" % park[1] if park else "", a.id))


if __name__ == "__main__":
    main()
