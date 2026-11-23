# Vacation Countdown

The other full-screen app this image can be built around (instead of the chess
clock): a countdown to a trip, drawn as a photograph of the ship at sea that
lives through the day.

* **The ship** is a real photo, with dusk and night versions graded from it on
  a desktop. The light follows the clock: day, a golden dusk, a starry night.
* **At night** cabin windows switch on and off one at a time, easing like
  lamps. Fireworks go up behind the ship: a few at random through the night,
  a two-minute show at a set time each night, both, or none (Settings).
* **The sea** ripples, calm right under the hull; foam runs along the
  waterline (heaviest at the bow wave) and a wake streams away behind the stern.
  Light smoke drifts from the funnels.
* **In the day** cloud shadows drift over the sea, gulls cross now and then, a
  pod of dolphins leaps ahead of the bow, a raft whooshes along the AquaDuck,
  and a pennant streams from the mast.
* **The countdown** is a flip clock at the top: split-flap cards with the
  number of days left. At midnight the changed cards fold over, and they flip
  once when the app starts.

## How it's built

The board's ARM9 is far too slow for this in Python (Pillow manages about 5
frames a second of sea and runs out of memory with the images loaded), so the
drawing is a small C library, `fx/vacfx.c`, that `vacation.py` loads with
ctypes. The library owns the images and redraws only what changes each frame:
the sea (distant rows less often, as they barely move), switching windows,
where particles and cards were and are. Measured on the Lichee Pi Nano: about
25 frames a second, with the CPU busy 92% of the time at the stock 408 MHz and
71% at 600 MHz.

`vacation.py` decides what to show: the number of days, the time of day, when
fireworks go off. It doesn't use Pillow at all, to leave the memory for the
images (about 15 MB for the whole app): even the Settings pages are drawn by the
C library, from text pre-drawn on a desktop (`ui/ui.bin.gz`, made by
`tools/themegen/build_ui.py`), so Settings opens in about half a second.

The panel shows 18-bit colour (6 bits a channel), which bands smooth gradients
like the sky; everything sent to the screen is dithered first (a fixed 2x2
pattern, so still areas stay still). It costs about 1% of the CPU.

## Files

This is an app ([docs/apps.md](../docs/apps.md)): `install.sh` lays it out in `/apps/vacation` on
the board, with the same folders as here. Its settings, saved time and log are in
`/apps/data/vacation`.

| In this folder | | |
|---|---|---|
| `run` | | starts it (`/etc/init.d/S99app` runs it, and restarts it if it exits); log in `/apps/data/vacation/vacation.log` |
| `vacation.py` | | the app: the countdown, and the active module's screens in turn with it |
| `modules.py` | | finds the active module and loads its scene and screens (see *Modules* below) |
| `fx/vacfx.c` | `fx/libvacfx.so` | the drawing |
| `vacation_settings.py` | | the Settings pages (drawn by the C library) |
| `vacation_layout.py` | | where everything goes on them, and their text (shared with `tools/themegen/build_ui.py`) |
| `ui/ui.bin.gz` | | their text and arrows, pre-drawn in Cormorant Garamond (SIL OFL, `fonts/OFL.txt`) |
| `vacation_touch.py` | | the touchscreen (the NS2009 chip, as in the chess clock) |
| `vacation_wifi.py` | | Settings > WiFi |
| `service` | | starts the active module's `service` beside the countdown (when the kernel has WiFi) |
| `modules/cruise/` | `/apps/data/vacation/cruise/` | the cruise module: the ship, the fleet map, live AIS positions (below) |
| `vacation.conf` | `/apps/data/vacation/vacation.conf` | settings, and the touchscreen calibration (copied the first time it runs) |
| `native/bench_water.c` | | the speed test the design came from (not installed) |

## Modules

What the countdown counts down to is a **module**: a whole trip, in a folder of its own in
`modules/`. `vacation.conf`'s `MODULE` picks one (`cruise` by default); `modules.py` loads it.

| A module has | | |
|---|---|---|
| `module.json` | | its id, name, version, the host `api` it was made for, its scene and its screens |
| a **scene** | `scenes/NAME/` | what's behind the countdown (`THEME` picks one, else module.json's default) |
| **screens** | e.g. `map.py` | shown in turn with the countdown: a class taking the app, with `run(seconds)`; module.json names its file and class and the settings for its seconds and on/off |
| a **service** | `service` | its background job, e.g. fetching data; run in the module's folder with `MODULE_DATA` set |
| its **data** | `/apps/data/vacation/ID/` | whatever it fetches or saves (`MODULE_DATA`, or `app.module.data_dir` for a screen) |
| **settings** | module.json `settings` | its page in Settings > Theme (below) |

The service writes, the screen reads: a dead network shows as old data, never a frozen screen.

**Settings > Theme** is the active module's page. Its first `settings` entry: `key` (the
vacation.conf setting it writes), `label` and `note`, `type` `one` (pick one) or `many` (pick any;
stored joined with `|`), and its options: listed (`options`, with `strip` taken off their front on the
chips), or the `rides` names in a file the service writes (`options_from`; its `*_example` version
beside the module until then). `short_names` in module.json: shorter names for long ones, on the chips
and the module's screens. Text from data is drawn letter by letter (`vacation_text.py`).

A scene's `theme.json` lists the drawing library's effects it has (`effects`: `water`, `wake`,
`smoke`, `gulls`, `dolphins`, `raft`); without the list, all of them (the ship). Fireworks, the window
light and the cards are every scene's.

**The cruise** (`modules/cruise/`): the Disney Dream scene (`scenes/dream/`, plates, window light and
cards made by `tools/themegen`; `scenes/dream-blender/` is the Blender-rendered version, not
installed), the fleet map (`map.py`, its Caribbean chart in `map/`, made by
`tools/themegen/build_map.py`), and live ship positions from AIS (`ais.py`, aisstream.io) into
`/apps/data/vacation/cruise/ships.csv`. AIS needs WiFi and an API key in
`/apps/data/vacation/cruise/ais.key`. Until it has them, the map shows `ships_example.csv`
(`tools/send_ships.py` puts a file there over USB).

**The castle** (`modules/castle/`): Cinderella Castle at Magic Kingdom (`scenes/magic-kingdom/`,
rendered from the user's model by `tools/themegen/castle/build_castle.sh`: day, dusk and night from
one camera, a light AI detail pass over all but the castle, parchment cards, the windows' light),
with no sea or smoke; the wait-times board (`board.py`); and ride waits, park hours and show times
from ThemeParks.wiki (`waits.py`, free, no key) into `/apps/data/vacation/castle/waits.json`, else
`waits_example.json`. Settings > Theme picks the rides the board shows (`RIDES`); `SHOW_NAME` the
fireworks show it names (Happily Ever After); `PARK` another park's ThemeParks.wiki id.

Still in the host: the cruise's pre-drawn text (ship names) in `vacation_layout.py`, and the countdown's
date setting (Settings' "Sail date"), shared by every module.

## Putting it on the board

Every image has it. To make it the one that starts at first boot, build with
`--build-arg APP=vacation`; on the board, `app vacation` switches to it. To try a change without
reflashing: `tools/deploy_app.py vacation`.

## Settings

**Press and hold** the picture for two seconds (a bar fills under the cards) for Settings.
Page one: the sail date, and today's date and time (the board has no clock battery; the app also
saves the time every five minutes and puts it back at start-up, so after a power cut it's only
behind by however long the power was off), and Calibrate touch. **Fireworks ›** opens page two:
when the fireworks go up (random, a nightly show, both, or off), how often the random ones do,
and the show's time. Save or Cancel goes back to the countdown.

`/apps/data/vacation/vacation.conf`, `KEY=VALUE` lines:

| Key | Default | |
|---|---|---|
| `SAIL_DATE` | `2027-02-16` | the day it counts down to |
| `MODULE` | `cruise` | the trip: a folder in `modules/` (see *Modules*) |
| `THEME` | `dream` | the module's scene: a folder in its `scenes/` |
| `LIGHTS_PER_MIN` | `90` | cabin windows switching per minute |
| `FIREWORKS_MODE` | `random` | `random` (a few rockets now and then through the night), `show` (a two-minute show every night at `FIREWORKS_SHOW_TIME`), `both`, or `off` |
| `FIREWORKS_EVERY_MIN` | `15` | how often (on average) the random ones go up at night |
| `FIREWORKS_SHOW_TIME` | `21:00` | the nightly show (24-hour) |
| `DITHER` | `1` | dither for the 18-bit panel (`0` turns it off) |
| `CPU_MHZ` | empty | set the CPU clock at start-up, e.g. `600`. The log's `self-check` line, once a minute, reports if the CPU starts making mistakes |

The board has no clock battery or network: set the date and time in Settings (until the
protoboard's WiFi can fetch it).

## Trying it on a desktop

The library builds on macOS or Linux and draws into a plain file instead of the screen:

```sh
clang -O2 -shared -fPIC -o /tmp/libvacfx.dylib vacation/fx/vacfx.c -lz
VACATION_LIB=/tmp/libvacfx.dylib VACATION_FB=/tmp/fb.raw APP_DATA=/tmp/vacation-data \
VACATION_CONF=vacation/vacation.conf VACATION_HOUR=22 VACATION_FIREWORKS=1 VACATION_FRAMES=100 python3 vacation/vacation.py
python3 -c "from PIL import Image; Image.frombytes('RGB',(800,480),open('/tmp/fb.raw','rb').read(),'raw','BGRX').save('/tmp/frame.png')"
```

A preview video: add `VACATION_SIM_CLOCK=0 VACATION_SIM_END=20 VACATION_RECORD=/tmp/v.raw`
(and `VACATION_DEMO=gulls@1,dolphins@3,raft@5` to set the daytime touches off early, or
`VACATION_TOUCH_SCRIPT=FILE` for scripted presses, see `vacation_touch.py`), then
`ffmpeg -f rawvideo -pix_fmt bgra -s 800x480 -r 25 -i /tmp/v.raw v.mp4`.

`VACATION_HOUR` fixes the time of day, `VACATION_DAYLAPSE=90` runs a day in 90
seconds, `VACATION_STATS=1` with `VACATION_LOG_SECS=10` prints the time each
drawing stage takes.

## Not done yet

The swipe and horn gestures (APDS-9960), the horn sound, the ship-position map
that alternates with the countdown, theme choice in Settings, and backlight
brightness by time of day.
