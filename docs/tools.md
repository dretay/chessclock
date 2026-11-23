# Development tools

`pip install -r tools/requirements.txt` (pyserial, Pillow) first.

## Talking to the board — `tools/board/`

They use the board's shell over a serial line: the board's own micro-USB port plugged into the Mac
when it is (Linux's USB serial gadget: by far the fastest, and picked by itself), otherwise a 3.3 V
USB-serial adapter on the Nano's UART0 (115200 baud; login `root` / `root`). `CLOCK_SERIAL` picks a
port by name.

| Tool | |
|---|---|
| `deploy_app.py [--use] NAME` | put an app (`chess`, `vacation`) on the board without reflashing: lays it out with its own `install.sh` (compiling its C for the board, with the build tree's compiler) and copies the changed files |
| `push_to_board.py LOCAL REMOTE` | copy files or folders to the board, checksum-verified, skipping unchanged ones, the app stopped meanwhile |
| `run_on_board.py "COMMAND" ...` | run shell commands on the board and print the output (logs in first if needed) |
| `flash_sd.sh [--all] [--uboot] DIR` | write a build to the SD card (macOS): see [building](building.md) |
| `fast_serial.py` | switch UART0 to 1562500 baud until the next reboot (then `CLOCK_BAUD=1562500`): ~13x faster copying when the USB port isn't an option |
| `boot_time.py [--bench URL DEVICE CH]` | time a boot from power-on, stage by stage (`--bench` switches the power through a lab-bench server's API) |

## Building — `tools/build/`

`build.sh` (and `buildroot-make.sh`, which runs inside the container): [building](building.md).

## Checking — `tools/test/check.py`

Checks the vacation countdown and its modules on a desktop, with the device's own drawing code:
every `module.json` and the files it names, that all the Python compiles, and renders of each
module (the countdown at noon and at night, and its screens) on the preview clock, so the same
code gives the same frames. Before a change that shouldn't change what's on screen:

```sh
tools/test/check.py --save before        # renders, kept as the baseline "before" (build/test/)
# ... the change ...
tools/test/check.py --compare before     # the same renders, compared pixel for pixel
```

A difference is reported with a diff image beside the render. (Needs a C compiler, zlib and Pillow.)

## Art — `tools/themegen/`

Makes the vacation countdown's scenes and Settings text on a desktop: the cruise's ship
(`cruise/`, from a photo) and Caribbean map, the castle (`castle/`, from a 3D model in Blender, with
a local Stable Diffusion detail pass), the pre-drawn text (`build_ui.py`). Its
[README](../tools/themegen/README.md); and the castle's `tools/themegen/castle/build_castle.sh`.

## WiFi — `tools/wifi/`

The ESP32's firmware: [wifi](wifi.md).

## The apps' own

`clock/tools/simulate.py` (the clock's animations and touch handling against an in-memory screen)
and `clock/tools/check_games.py` (every game in `clock/games.pgn` replays: run it after adding one);
`vacation/modules/cruise/tools/send_ships.py` (ship positions to the board over USB, for the map
without WiFi).
