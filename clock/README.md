# Chess Clock

The application this image is built around: a full-screen clock for the
Lichee Pi Nano's 5" 800x480 touch screen.

* **Left:** a chessboard replaying famous games, one sliding move every 3
  seconds. Each game starts with its name and players in a caption.
  Captured pieces arc off the board into the tray; a pawn promoting gets a
  gold ring burst; and when a game ends in checkmate, the beaten king topples
  over and a caption names the winner.
* **Right:** a walnut chess-clock case with the hour and minutes on two clock
  faces, and a felt tray holding the pieces each side has lost.
* **Every minute** the case's plunger dips and the minute face flips over
  like a split-flap display. **On the hour** a pawn marches up the hour face
  and promotes into the new hour.
* **Press and hold the screen** for two seconds for Settings - the plunger
  sinks while you hold, and Settings opens when it reaches the bottom, so a
  passing tap (or a curious child) can't change anything. A quick tap shows
  the game's name and players again. In Settings: set the time, adjust daytime and
  night-time brightness (live preview while dragging), or turn the display
  upside down. Brightness eases between the day and night levels over three
  minutes, like a lamp dimming.

It is a single Python program drawing with Pillow straight to the Linux
framebuffer (`/dev/fb0`) - no X11, Wayland or SDL. The board has 32MB of RAM,
so it never holds a full-screen image: board squares and parts of the clock
case are drawn and written separately, and animation frames are prepared in
advance and written as small changed strips. Animations run at up to 30
frames a second.

Starting up is kept short (about 5 seconds) by installing the program
pre-compiled, and by saving the drawn chess pieces and the Settings screen to
the SD card (`/var/lib/fbclock/cache`) the first time they are drawn. The
first start after flashing takes a few seconds longer while it fills the
cache; the cache clears itself whenever the program changes.

## Files

| In this folder | Installed as | |
|---|---|---|
| `fbclock.py` | `/usr/lib/python3.11/site-packages/fbclock.pyc` | the clock, installed as a pre-compiled module |
| `fbclock` | `/usr/bin/fbclock` | starts it |
| `games.pgn` | `/usr/share/fbclock/games.pgn` | the games it replays (standard PGN; add your own) |
| `splash/*.raw.gz` | `/usr/share/fbclock/` | boot splash, ready-made in the screen's pixel format, one per orientation |
| `fbclock.conf` | `/etc/fbclock.conf` | default settings and touch calibration |
| `init.d/S00splash` | `/etc/init.d/S00splash` | shows the splash early in boot, at a dimmed brightness |
| `init.d/S99fbclock` | `/etc/init.d/S99fbclock` | starts the clock and restarts it if it ever exits |

The Buildroot package in [`package/fbclock`](../package/fbclock) installs
these; `BR2_PACKAGE_FBCLOCK=y` in the defconfigs enables it.

## Settings

Settings live in `/etc/fbclock.conf` as `KEY=VALUE` lines. The Settings screen
writes `ROTATE`, `DAY_BRIGHTNESS` and `NIGHT_BRIGHTNESS` there itself (safely:
a power cut mid-save can't corrupt it); the rest can be edited by hand.

| Key | Default | |
|---|---|---|
| `TOUCH_X_MIN`, `TOUCH_X_MAX`, `TOUCH_Y_MIN`, `TOUCH_Y_MAX` | measured for this panel | raw touch readings (0-4095) at the screen edges; swap a pair to flip an axis |
| `TOUCH_SWAP_XY` | `0` | `1` if moving left-right changes the raw y reading |
| `ROTATE` | `0` | `1` turns the display (and touch) upside down |
| `DAY_BRIGHTNESS`, `NIGHT_BRIGHTNESS` | `100`, `30` | percent (5-100) |
| `NIGHT_START`, `NIGHT_END` | `21:00`, `07:00` | when night-time brightness applies (24-hour) |

Reflashing the SD card resets these to the image's defaults.

The board has no battery-backed clock, so the time resets to 1970 at every
power-up (and counts as night) until it is set in Settings.

## Logs and troubleshooting

The clock logs to `/var/lib/fbclock/fbclock.log` on the SD card, with the
previous run's log in `fbclock.log.1`. Every accepted touch is logged with its
screen position, every rejected one (noise) with its readings, and if the
clock ever exits the log says so before it is restarted.

```sh
/etc/init.d/S99fbclock stop|start|restart
fbclock --touch-debug                         # print raw and screen touch positions
```

To try a changed `fbclock.py` on the board without reflashing, copy it to
`/usr/lib/python3.11/site-packages/` (next to `fbclock.pyc`, which it then
takes precedence over) and restart the clock; `tools/push_to_board.py` does
the copying over the serial console. `tools/simulate.py` checks the
animations and touch handling on a desktop first.

To recalibrate the touch screen: stop the clock, run `--touch-debug`, tap near
each corner, and put the raw readings into `fbclock.conf`.

## Hardware notes

* **Touch:** the resistive film on the 40-pin LCD connector goes to the
  board's on-board NS2009 touch chip (I2C address 0x48 on TWI0, pins
  PE11/PE12), not to the F1C100s's own touch controller. The clock polls it
  through `/dev/i2c-0`. The board has no pull-ups on that bus, so the device
  tree enables the pins' internal ones.
* **Brightness:** the backlight driver's enable pin (PE6, "PWM1") is driven as
  a 500Hz PWM backlight, set through `/sys/class/backlight`.
* **Rotation** is applied when pixels are written to the screen and when
  touch positions are read, so everything else draws the right way up.

## Trying it on a desktop

The program can render a single frame to a PNG, which is how most of its
look was developed. It needs Pillow and the DejaVu fonts:

```sh
FBCLOCK_FONTS=/path/to/dejavu/ttf FBCLOCK_GAMES=clock/games.pgn \
FBCLOCK_PREVIEW=preview.png python3 clock/fbclock.py
```

Add `FBCLOCK_PLY=20` to show a game 20 moves in, or `FBCLOCK_PREVIEW_SETTER=1`
for the Settings screen.

The splash images are regenerated with
`python3 clock/fbclock.py --make-splash clock/splash 800x480x32` (on the board,
for pixel-exact output, then copied back).
