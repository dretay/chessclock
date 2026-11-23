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
| `vacation.py` | | the app |
| `fx/vacfx.c` | `fx/libvacfx.so` | the drawing |
| `themes/dream/` | | the Disney Dream theme: plates, window light, cards (made by `tools/themegen`) |
| `vacation_settings.py` | | the Settings pages (drawn by the C library) |
| `vacation_layout.py` | | where everything goes on them, and their text (shared with `tools/themegen/build_ui.py`) |
| `ui/ui.bin.gz` | | their text and arrows, pre-drawn in Cormorant Garamond (SIL OFL, `fonts/OFL.txt`) |
| `vacation_touch.py` | | the touchscreen (the NS2009 chip, as in the chess clock) |
| `vacation_map.py`, `map/` | | the fleet map and its Caribbean chart |
| `vacation_wifi.py` | | Settings > WiFi |
| `ais.py`, `service` | `/apps/data/vacation/ships.csv` | the map's live ship positions from AIS (aisstream.io), run beside the countdown; needs WiFi and an API key in `/apps/data/vacation/ais.key` |
| `vacation.conf` | `/apps/data/vacation/vacation.conf` | settings, and the touchscreen calibration (copied the first time it runs) |
| `native/bench_water.c` | | the speed test the design came from (not installed) |
| `themes/dream-blender/` | | the Blender-rendered version of the ship (not installed) |

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
| `THEME` | `dream` | a folder in `themes/` |
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
VACATION_LIB=/tmp/libvacfx.dylib VACATION_FB=/tmp/fb.raw VACATION_THEME_DIR=vacation/themes/dream \
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
