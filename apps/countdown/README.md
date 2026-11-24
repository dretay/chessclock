# Countdown runtime

The engine the countdown apps run on: the [cruise](../cruise) (the Disney Dream at sea, the fleet
map) and the [castle](../castle) (Cinderella Castle, live ride waits). Each of those is an app of its
own ([docs/apps.md](../../docs/apps.md)) that brings its scene, screens and settings; this runtime
draws them: a countdown to a trip, on a picture of where you're going that lives through the day.
How a countdown app is put together: [docs/countdown.md](../../docs/countdown.md).

* **The picture** follows the clock: day, a golden dusk, a starry night, graded on a desktop.
* **At night** windows switch on and off one at a time, easing like lamps. Fireworks go up: a few at
  random through the night, a two-minute show at a set time each night, both, or none (Settings).
* **The cruise's sea** ripples, calm right under the hull; foam runs along the waterline and a wake
  streams away behind the stern; smoke drifts from the funnels; gulls, dolphins and a raft on the
  AquaDuck now and then. (A scene says which of these it has: the castle has none of them.)
* **The countdown** is a flip clock: split-flap cards with the number of days left. At midnight the
  changed cards fold over, and they flip once when the app starts.

## How it's built

The board's ARM9 is far too slow for this in Python (Pillow manages about 5 frames a second of sea
and runs out of memory with the images loaded), so the drawing is a small C library, `fx/vacfx.c`,
that `vacation.py` loads with ctypes. The library owns the images and redraws only what changes each
frame. Measured on the Lichee Pi Nano: about 25 frames a second, with the CPU busy 92% of the time at
the stock 408 MHz and 71% at 600 MHz.

`vacation.py` decides what to show: the number of days, the time of day, when fireworks go off, which
of the app's screens is next. It doesn't use Pillow at all, to leave the memory for the images: even
the Settings pages are drawn by the C library, from text pre-drawn on a desktop (`ui/ui.bin.gz`, made
by `tools/themegen/build_ui.py`), so Settings opens in about half a second.

The panel shows 18-bit colour (6 bits a channel), which bands smooth gradients like the sky;
everything sent to the screen is dithered first (a fixed 2x2 pattern, so still areas stay still).

## Files

An app of its own (`/apps/countdown` on the board), but one that's never started by itself: it has
no `run`, and isn't in the app picker. A countdown app's `run` is `exec /apps/countdown/launch`.

| In this folder | | |
|---|---|---|
| `launch` | | starts the countdown for the app it's run from (its folder, its `APP_DATA`) |
| `vacation.py` | | the countdown, and the app's screens in turn with it |
| `apps.py` | | the app: its app.json, scene and screens, and its settings file (made the first time) |
| `API` | | the app api this runtime provides (`2`): modinstall checks an app against it |
| `countdown.conf` | | the settings every countdown app starts with (and the app's own `defaults.conf`) |
| `native/bench_water.c` | | the speed test the design came from (not installed) |

It runs on the **system package** (`apps/system`, `/apps/system`), which every app shares: the drawing
library (`fx/vacfx.c`), the Settings pages (`vacation_settings.py`, their layout and pre-drawn text:
`vacation_layout.py`, `ui/ui.bin.gz`), text, touch and WiFi (`vacation_text.py`, `vacation_touch.py`,
`vacation_wifi.py`), Device settings (`device.py`), the app picker and Get apps (`picker.py`,
`catalog.py`), and the loading dots (`fx/splashanim.c`).

## Settings

**Press and hold** the picture (or the app's own screen: the wait-times board, the fleet map) for two
seconds (a bar fills under the cards) for Settings: the trip's date (the app's name for it: "Sail
date", "Park day"). **Fireworks ›**: when the fireworks go up (random, a nightly show, both, or off), how
often the random ones do, and the show's time. **Theme ›**: the app's own setting (the ship the map
follows, the rides the wait-times board shows). **Device ›**: the device's settings, every app's (today's
date and time: the board has no clock battery, so the time is saved every five minutes and put back at
start-up, and with WiFi it's set from the network; Display: day and night brightness, which the
countdown eases between at the night hours, 9 PM to 7 AM by default, and Calibrate touch; WiFi).
**Apps ›**: the app picker (and Get apps, the catalog, with WiFi). Save or Cancel goes back to the
countdown.

Each countdown app keeps its own settings, `/apps/data/<app>/countdown.conf` (so each trip has its
own date), made the first time it runs: from the old shared `vacation.conf` if the board had one
(its touch calibration and preferences), else another countdown app's, else `countdown.conf` here;
plus the app's own `defaults.conf`. `KEY=VALUE` lines:

| Key | Default | |
|---|---|---|
| `TRIP_DATE` | `2027-02-16` | the day it counts down to (`SAIL_DATE` in older settings works too) |
| `THEME` | empty | the app's scene: a folder in its `scenes/` (empty: its default) |
| `LIGHTS_PER_MIN` | `90` | windows switching per minute |
| `FIREWORKS_MODE` | `random` | `random` (a few rockets now and then through the night), `show` (a two-minute show every night at `FIREWORKS_SHOW_TIME`), `both`, or `off` |
| `FIREWORKS_EVERY_MIN` | `15` | how often (on average) the random ones go up at night |
| `FIREWORKS_SHOW_TIME` | `21:00` | the nightly show (24-hour) |
| `COUNTDOWN_SECS` | `60` | how long the countdown shows between the app's own screens |
| `DITHER` | `1` | dither for the 18-bit panel (`0` turns it off) |
| `CPU_MHZ` | empty | set the CPU clock when this app starts (the base system already runs it at 600 MHz: [system](../../docs/system.md)). The log's `self-check` line, once a minute, reports if the CPU starts making mistakes |
| `TOUCH_*` | the 5" panel's | the touchscreen calibration: the device's, in `/apps/data/device.conf` (Settings > Display > Calibrate touch measures it) |

The apps' own: [docs/countdown.md](../../docs/countdown.md).

## Trying it on a desktop

The library builds on macOS or Linux and draws into a plain file instead of the screen:

```sh
clang -O2 -shared -fPIC -o /tmp/libvacfx.dylib apps/countdown/fx/vacfx.c -lz
cat apps/countdown/countdown.conf apps/castle/defaults.conf > /tmp/castle.conf
VACATION_APP=apps/castle VACATION_LIB=/tmp/libvacfx.dylib VACATION_FB=/tmp/fb.raw APP_DATA=/tmp/castle-data \
VACATION_CONF=/tmp/castle.conf VACATION_HOUR=22 VACATION_FIREWORKS=1 VACATION_FRAMES=100 python3 apps/countdown/vacation.py
python3 -c "from PIL import Image; Image.frombytes('RGB',(800,480),open('/tmp/fb.raw','rb').read(),'raw','BGRX').save('/tmp/frame.png')"
```

A preview video: add `VACATION_SIM_CLOCK=0 VACATION_SIM_END=20 VACATION_RECORD=/tmp/v.raw`
(and `VACATION_DEMO=gulls@1,dolphins@3,raft@5` to set the cruise's daytime touches off early, or
`VACATION_TOUCH_SCRIPT=FILE` for scripted presses, see `vacation_touch.py`), then
`ffmpeg -f rawvideo -pix_fmt bgra -s 800x480 -r 25 -i /tmp/v.raw v.mp4`. `VACATION_HOUR` fixes the
time of day, `VACATION_DAYLAPSE=90` runs a day in 90 seconds, `VACATION_STATS=1` with
`VACATION_LOG_SECS=10` prints the time each drawing stage takes. `tools/test/check.py` does all of
this for every countdown app, and compares the frames with a baseline.

## Not done yet

The swipe and horn gestures (APDS-9960), and the horn sound.
