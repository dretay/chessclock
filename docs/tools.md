# Development tools

The tools need pyserial and Pillow. Homebrew's Python won't take packages directly, so give the
project a virtualenv of its own (ignored by git), and activate it in each new terminal:

```sh
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt     # once
source .venv/bin/activate                                                    # then python3 is this one
```

## Previewing apps on the Mac — `tools/preview/`

```sh
tools/preview/preview.py castle          # opens the App Preview window (--browser: a page instead)
```

The real app runs on the Mac (the countdown runtime with a countdown app, or the chess clock), with
a plain file for its screen; the **App Preview** window (`viewer.swift`, a small native Mac app built
the first time with the Xcode command-line tools' `swiftc`) shows that screen at its own frame rate
and makes the mouse the touchscreen (click to tap, hold two seconds for Settings, drag the sliders).
Saving a file in the app or the runtime restarts it (the drawing library is recompiled when
`fx/vacfx.c` changes). Its menus: **App** (the apps ⌘1–3, Restart ⌘R), **Time** (morning, noon, dusk,
evening, night; Pretend It's… ⌘D, e.g. the trip's last day), **Data** (the app's background job with
the Mac's network ⌘L: live ride waits; AIS with a key in `build/preview/data/cruise/ais.key`),
**View** (actual or double size, Keep on Top ⌘T, the log ⌘J, a screenshot to the Desktop ⌘S).
Closing the window stops the preview. `--browser` (or no `swiftc`) shows the same in a page at
http://localhost:8800. Settings > Apps opens the real app
picker. Each app keeps its own settings and data in `build/preview/data/`. The chess clock's DejaVu
fonts are copied once from the board's build tree (`tools/build/build.sh` first, or `FBCLOCK_FONTS`).

## Talking to the board — `tools/board/`

They use the board's shell over a serial line: the board's own micro-USB port plugged into the Mac
when it is (Linux's USB serial gadget: by far the fastest, and picked by itself), otherwise a 3.3 V
USB-serial adapter on the Nano's UART0 (115200 baud; login `root` / `root`). `CLOCK_SERIAL` picks a
port by name.

| Tool | |
|---|---|
| `deploy.py [--signed] [--use NAME] NAME ...` | put apps (`chess`, `countdown`, `castle`, `cruise`) on the board without reflashing: laid out by `tools/apps/layout.py` (compiled for the board where needed), then copied (only what changed) or, `--signed`, packed, signed and installed by the board's `modinstall` ([apps](apps.md)) |
| `push_to_board.py LOCAL REMOTE` | copy files or folders to the board, checksum-verified, skipping unchanged ones, the app stopped meanwhile |
| `run_on_board.py "COMMAND" ...` | run shell commands on the board and print the output (logs in first if needed) |
| `flash_sd.sh [--all] [--uboot] DIR` | write a build to the SD card (macOS): see [building](building.md) |
| `fast_serial.py` | switch UART0 to 1562500 baud until the next reboot (then `CLOCK_BAUD=1562500`): ~13x faster copying when the USB port isn't an option |
| `boot_time.py [--bench URL DEVICE CH]` | time a boot from power-on, stage by stage (`--bench` switches the power through a lab-bench server's API) |

## Building — `tools/build/`

`build.sh` (and `buildroot-make.sh`, which runs inside the container): [building](building.md).

## Checking — `tools/test/check.py`

Checks the apps on a desktop, with the device's own drawing code: every `app.json` and the files it
names, that all the Python compiles, the installer's tests (`test_modinstall.py`), the app picker (a
render, and a tap that picks), and renders of each countdown app (the countdown at noon and at night,
and its screens) on the preview clock, so the same code gives the same frames. Before a change that shouldn't change what's on screen:

```sh
tools/test/check.py --save before        # renders, kept as the baseline "before" (build/test/)
# ... the change ...
tools/test/check.py --compare before     # the same renders, compared pixel for pixel
```

A difference is reported with a diff image beside the render. (Needs a C compiler, zlib and Pillow.)

## Art — `tools/themegen/`

Makes the countdown apps' scenes, pictures and Settings text on a desktop: the cruise's ship
(`cruise/`, from a photo) and Caribbean map, the castle (`castle/`, from a 3D model in Blender, with
a local Stable Diffusion detail pass), the pre-drawn text (`build_ui.py`). Its
[README](../tools/themegen/README.md); and the castle's `tools/themegen/castle/build_castle.sh`.

## Apps — `tools/apps/`

`layout.py NAME [DEST]` (an app's files as they go on the board: the one rule the image, deploy and
packing share), `pack.py NAME [--key KEY]` (its tarball and signed statement, for `modinstall`) and
`keygen.sh` (the signing key, once): [apps](apps.md).

## WiFi — `tools/wifi/`

The ESP32's firmware: [wifi](wifi.md).

## The apps' own

`apps/chess/tools/simulate.py` (the clock's animations and touch handling against an in-memory screen)
and `apps/chess/tools/check_games.py` (every game in `apps/chess/games.pgn` replays: run it after adding one);
`apps/cruise/tools/send_ships.py` (ship positions to the board over USB, for the map
without WiFi).
