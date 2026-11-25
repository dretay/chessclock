# Countdown apps

A countdown app is a whole trip: an app of its own ([apps](apps.md)) on the countdown runtime
(`apps/countdown`, [its README](../apps/countdown/README.md)), which draws the countdown, the picture
and Settings. The app brings the trip:

| A countdown app has | | |
|---|---|---|
| `app.json` | | its id, name, version, the runtime and api it needs, its scene, screens, settings and countdown wording |
| `run` | | `exec /apps/countdown/launch`: the runtime, for this app |
| a **scene** | `scenes/NAME/` | the picture behind the countdown (`THEME` picks one, else app.json's default) |
| **screens** | e.g. `map.py` | shown in turn with the countdown: a class taking the runtime's App, with `run(seconds)`; app.json names its file and class and the settings for its seconds and on/off |
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

A scene folder holds what the drawing library (`apps/countdown/fx/vacfx.c`) loads: `day.rgb.gz`,
`dusk.rgb.gz`, `night.rgb.gz` (800x480 raw RGB plates, blended by the time of day), `mask.raw.gz`
(255 where it isn't sky: no water there, and fireworks go behind it), `lights.bin.gz` (the windows'
light: pixels, their light, their window, so windows switch one at a time at night), `cards.bin.gz`
(the flip-clock cards, the last day's colon and the banner for the day itself),
`settings_bg.rgb.gz` (the Settings screen's background) and `theme.json`:

- `horizon`: the sea's top (the ship), or where the fireworks go up from;
- `cards`: where the cards go (`center_x`, `top`, `gap`; `label_gap` -1: no DAYS label);
- `effects`: the library's scene effects it has (`water`, `wake`, `smoke`, `gulls`, `dolphins`,
  `raft`); without the list, all of them. Fireworks, window light and the cards are every scene's;
- the ship's own places, for those effects (`stacks`, `bow`, `stern`, `mast`, `tube`, scales), left
  out by a scene without them.

The generators are in `tools/themegen/` ([its README](../tools/themegen/README.md)): the cruise's from a
photo, the castle's from a 3D model (`tools/themegen/castle/build_castle.sh`).

## The two so far

**The cruise** (`apps/cruise/`): the Disney Dream (`scenes/dream/`; `scenes/dream-blender/` is a
Blender-rendered version, not installed), the fleet map (`map.py`, its Caribbean chart in `map/`, made
by `tools/themegen/build_map.py`), placing each Disney ship where its itinerary says: at a port
between its arrival and departure, or partway along the leg to the next (by sea, around Florida and
Cuba: `map/sea.bin`, from `tools/themegen/build_sea.py`). The schedules come from CruiseMapper's ship
pages, fetched over WiFi by `schedule.py` (the app's service: each ship about twice a day) into
`/apps/data/cruise/schedule.json`; until then the map shows `schedule_example.json` (a real fetch, its
times moved to now). It reads CruiseMapper's page layout: if they change it, the log says "couldn't
read" and the map keeps the last schedules. Settings > Theme: the ship the map follows (`MAP_SHIP`).

**The castle** (`apps/castle/`): Cinderella Castle at Magic Kingdom (`scenes/magic-kingdom/`, rendered
from a 3D model: day, dusk and night from one camera, a light AI detail pass over all but the castle,
parchment cards, the windows' light), with none of the ship's effects; the wait-times board
(`board.py`); and ride waits, park hours and show times from ThemeParks.wiki (`waits.py`, free, no
key; fetched every 5 minutes, then it exits, so it takes memory only for the seconds of a fetch) into
`/apps/data/castle/waits.json`, else `waits_example.json`. Settings > Theme: the rides the board shows
(`RIDES`); `SHOW_NAME` the fireworks show it names (Happily Ever After); `PARK` another park's
ThemeParks.wiki id.

## Checking

`tools/test/check.py`: every app.json and its files, the installer's tests, the app picker, and
renders of each countdown app with the device's own drawing code, compared pixel for pixel with a
baseline ([tools](tools.md)).
