# Countdown apps

A countdown app is a whole trip: an app of its own ([apps](apps.md)) on the countdown runtime
(`apps/countdown`, [its README](../apps/countdown/README.md)), which draws the countdown, the picture
and Settings. The app brings the trip:

| A countdown app has | | |
|---|---|---|
| `app.json` | | its id, name, version, the runtime and api it needs, its scene, screens, settings and countdown wording |
| `run` | | `exec /apps/countdown/launch`: the runtime, for this app |
| a **scene** | `scenes/NAME/` | the picture behind the countdown (`THEME` picks one, else app.json's default) |
| **screens** | `"type"`s | shown in turn with the countdown: the runtime's screen types (waits, weather, ships: see Screens below), or a class of the app's own taking the runtime's App, with `run(seconds)` |
| a **service** | `service` | its background job, e.g. fetching data, beside it (S99app runs it with `APP_DATA`); every one so far needs the network, and sleeps on a kernel without WiFi |
| its **settings and data** | `/apps/data/ID/` | `countdown.conf` (made the first time: [the runtime's README](../apps/countdown/README.md#settings)), and whatever it fetches (`APP_DATA`, or `app.module.data_dir` for a screen) |
| `defaults.conf` | | its own settings' first values |
| **settings** | app.json `settings` | its page in Settings > Theme (below) |
| `icon.rgb.gz` | | its picture in the app picker (`tools/themegen/app_icon.py`) |
| `splash.sh`, `splash/` | | its boot splash (`tools/themegen/app_splash.py`): its blurred scene, its name and "Starting", with the runtime's `splashanim` pulsing three dots after it until the countdown draws |
| desktop **tools** | `tools/` | helpers for the developer (e.g. sending data over USB); not installed |

The service writes, the screen reads: a dead network shows as old data, never a frozen screen.

## app.json

```json
{"id": "castle", "name": "Magic Kingdom", "version": "1.0.0", "runtime": "countdown", "api": 2,
 "exclude": ["scenes/*/preview.png"],
 "scene": {"engine": "scene", "dir": "scenes", "default": "magic-kingdom"},
 "screens": [{"id": "waits", "file": "board.py", "class": "WaitsScreen", "enabled": "WAITS", "secs": "WAITS_SECS"}],
 "settings": [{"key": "RIDES", "label": "Rides", "note": "...", "type": "many", "options_from": "waits.json"}],
 "countdown": {"date_label": "Park day", "after": "Already there", "time": "09:00"},
 "short_names": {"Tomorrowland Transit Authority PeopleMover": "PeopleMover"}}
```

- **runtime, api**: the runtime it runs on and the app api it was made for; `modinstall` won't
  install it without that runtime, or with one older than its api (the runtime's `API` file).
- **exclude**: its files that don't go on the board (besides `tools/` and caches).
- **countdown**: Settings' label for the trip's date (`TRIP_DATE`), what the header says once it's
  passed, and the time of day the last day counts down to (`TRIP_TIME` overrides).
- **settings** (Settings > Theme shows the first): `key` (the setting it writes), `label`, `note`,
  `type` `one` (pick one) or `many` (pick any; stored joined with `|`), and its options: listed
  (`options`; `strip` is taken off their front on the chips; `default`, `fallback` another setting to
  start from), or the `rides` names in a file the service writes (`options_from`; its `*_example`
  version beside the app until then).
- **short_names**: shorter names for long ones, on the chips and the app's screens. Text from data is
  drawn letter by letter, plain ASCII (`apps/countdown/vacation_text.py`).

## Scenes

A scene folder holds what the drawing library (`apps/system/fx/vacfx.c`) loads: `day.rgb.gz`,
`dusk.rgb.gz`, `night.rgb.gz` (800x480 raw RGB plates, blended by the time of day), `mask.raw.gz`
(255 where it isn't sky: no water there, and fireworks go behind it), `lights.bin.gz` (the windows'
light: pixels, their light, their window, so windows switch one at a time at night), `cards.bin.gz`
(the flip-clock cards, the last day's colon and the banner for the day itself),
`settings_bg.rgb.gz` (the Settings screen's background) and `theme.json`:

- `horizon`: the sea's top (the ship), or where the fireworks go up from;
- `cards`: where the cards go (`center_x`, `top`, `gap`; `label_gap` -1: no DAYS label), their size
  (`scale`, 0.4 to 1.3 of the cards as drawn; the last day's colon too), and three digits' size (`scale3`,
  of that);
- `water` (with a `water.raw.gz`: how much each pixel ripples, painted or found in the Scene Builder):
  `{"strength": 1.0, "speed": 1.0}`; without the file, the water is the sea below the horizon, off the
  ship (the cruise's);
- `smoke`: `{"points": [[x, y], ...], "scale": 0.8, "wind": 0, "rate": 4}`: smoke rising from those points
  (up to 8: a campfire, a chimney; scale: each puff's size and the plume's height, 0.5 a wisp to 1.3 a
  tall plume; wind -1 left to 1 right; rate 2 light to 8 heavy); without it, the
  ship's two funnels (`stacks`). `birds` in `effects`: now and then a few cross the sky, by day (the
  cruise's gulls, for any scene); `foam`: `{"points": [[x, y, r], ...], "amount": 1.0, "flow": "still" |
  "left" | "right" | "falling" | "toward"}`: white water at those points (up to 16: a waterfall's foot,
  rapids, surf; falling throws up spray), on the scene's own water if it has some, else wherever placed;
- `effects`: the library's scene effects it has (`water`, `wake`, `smoke`, `gulls`/`birds`, `dolphins`,
  `raft`, `twinkle`); without the list, all of them. Fireworks, window light and the cards are every
  scene's. `twinkle`: coloured lights on the subject at night (EPCOT's orb), from the scene's
  `twinkle.bin.gz` (their places, and each one's place on the sphere), fading in through dusk: a
  light show, its patterns in turn, crossfading (spin, rise, spiral, comet, wash, heartbeat, sparkle,
  waves, rings, blink); `show`: `{"program": [...], "secs": 12}` picks and orders them;
- the ship's own places, for those effects (`stacks`, `bow`, `stern`, `mast`, `tube`, scales), left
  out by a scene without them.

The generators are in `tools/themegen/` ([its README](../tools/themegen/README.md)): the cruise's from a
photo, the castle's from a 3D model (`tools/themegen/castle/build_castle.sh`). For a new app,
`photo_scene.py PHOTO APP [--crop X,Y,W,H] [--keep-mask]` makes the whole scene from one daytime photo:
dusk and night graded from it with their own skies, the sky found by itself (`mask.png` in
`tools/themegen/work/APP/`, to paint over and keep if it's wrong), packed into the app by
`scene_pack.py`. Its `scene.json` there holds the rest: the horizon, the greeting, the cards' place,
and `"orb": {"cx", "cy", "r", "spacing"}` for twinkle lights on a sphere (with `twinkle_mask.png` to
leave out what's in front of it). With the previewer open on the app, it restarts with the new scene.

## The apps so far

**The cruise** (`apps/cruise/`): the Disney Dream (`scenes/dream/`; `scenes/dream-blender/` is a
Blender-rendered version, not installed), the fleet map (the runtime's "ships" screen type, its Caribbean chart in the app's `map/`, made
by `tools/themegen/build_map.py`), placing each Disney ship where its itinerary says: at a port
between its arrival and departure, or partway along the leg to the next (by sea, around Florida and
Cuba: `map/sea.bin`, from `tools/themegen/build_sea.py`). The schedules come from CruiseMapper's ship
pages, fetched over WiFi by the runtime's `ships/fetch.py` (the shared fetcher loop: each ship about twice a day) into
`/apps/data/cruise/schedule.json`; until then the map shows `schedule_example.json` (a real fetch, its
times moved to now). It reads CruiseMapper's page layout: if they change it, the log says "couldn't
read" and the map keeps the last schedules. Settings > Theme: the ship the map follows (`MAP_SHIP`).

**The castle** (`apps/castle/`): Cinderella Castle at Magic Kingdom (`scenes/magic-kingdom/`, rendered
from a 3D model: day, dusk and night from one camera, a light AI detail pass over all but the castle,
parchment cards, the windows' light), with none of the ship's effects, and the park's wait times.

**EPCOT** (`apps/epcot/`): the park's wait times, on a placeholder scene (a plain sky by day, dusk and
night) until its art is made.

**Screens** (runtime API 4): what shows in turn with the countdown is a list of screen types in the
app's `app.json` (`apps/countdown/screens.py`), any number, in order, each for its seconds:
`{"type": "waits"}` (a park's ride wait times), `{"type": "weather", "place": ..., "lat": ..., "lon":
..., "units": "F"}` (the forecast for planning a hike: now, which days bring rain or snow, and ten days
in cards, each with its rain (how likely) or snow (how much); the trip's day outlined in gold; from Open-Meteo, free, no key, credited on the screen; `apps/countdown/weather/`). An app's
`service` is `exec ../countdown/screens.sh`: the fetchers its screens need, one at a time, each as often
as its type says (ride waits every 5 minutes, the weather every half hour), so only one Python is ever
fetching. (A screen of an app's own: `{"file", "class"}`, as the cruise's fleet map, for now.)

**The parks' wait times** are the runtime's (`apps/countdown/parks/`), shared by every
park app: the board (`board.py`, the "waits" screen type), and ride
waits, park hours and show times from ThemeParks.wiki (`waits.py`, free, no key; fetched every 5
minutes by the shared fetcher loop (`screens.sh`), then it exits, so it takes memory only
for the seconds of a fetch) into `/apps/data/<app>/waits.json`, else the app's `waits_example.json`.
The park and its night show are the app's `app.json` `"park": {"id": ThemeParks.wiki id, "show": ...}`;
`"short_names"` shortens long ride names. Settings > Theme: the rides the board shows (`RIDES`);
`SHOW_NAME` and `PARK` in the app's settings override the show and park.

**A new one:** `python3 tools/apps/new.py ID --name NAME [--park PARK --show SHOW] [--weather PLACE]`
(e.g. `new.py epcot --name EPCOT --park EPCOT --show "Luminous The Symphony of Us"`; `new.py yosemite
--name Yosemite --weather "Yosemite Valley" --date-label "Trail day"`) makes the app with a placeholder
scene and, for a park, its wait times, for a place, its weather (the place looked up by name), each
with an example of them; it runs at once in the previewer. Real art goes
in `tools/themegen/work/ID/` (day, dusk and night pictures from one camera; optional mask.png,
windows.png, scene.json), packed into the app's scene by `tools/themegen/scene_pack.py`.

## Checking

`tools/test/check.py`: every app.json and its files, the installer's tests, the app picker, and
renders of each countdown app with the device's own drawing code, compared pixel for pixel with a
baseline ([tools](tools.md)).
