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
the Mac's network ⌘L: live ride waits, the ships' schedules),
**View** (actual or double size, Keep on Top ⌘T, the log ⌘J, the Controls ⌘K, a screenshot to the
Desktop ⌘S). Its **Controls** panel (and the page's): a time-of-day slider the scene follows as it's
dragged (no restart), "This Mac's clock", Fireworks / Nightly show buttons, the lights' show (all
the patterns in turn, or one held), and Edit lights: Erase (drag over them) or Add (click), with Undo,
on the photo being tried or the app's own scene.
Closing the window stops the preview.

"Find automatically" (the sky, water, where windows can be) asks an image model what each pixel is
(`tools/themegen/segment.py`: SegFormer-B2, trained on ADE20K: sky, tree, building, water, sea...), in the
AI environment `tools/themegen/work/aienv` (PyTorch: the castle's detail pass uses it too), on the Mac's
GPU, a few seconds; the model, about 100 MB, is downloaded once. Without that environment, the finders go
by colour and texture (rougher: trees can pass for windows, reflections hide water). "Clear all": the
found and the painted, for that effect.

Zoom the picture to work on small things (windows): the mouse wheel or a pinch (around the pointer), or
View › Zoom In / Out / to Fit (⌥⌘= ⌥⌘- ⌥⌘0),
and move around by dragging the picture (with nothing to paint or place; a click is still a tap), Option-
dragging or middle-button dragging (in any mode), two fingers on a trackpad, or the arrow keys; painting, boxes and taps all
work zoomed. After "Find automatically" (or a
new photo), what was found is outlined over the picture for a few seconds (Show all: everything for that effect,
found and painted). "Stay on
the scene" (Controls, and the Scene Builder, which turns it on): the app's other screens wait.

The **Scene Builder** panel (View › Scene Builder ⌘B; `tools/preview/builder.html`, in the window, or at
http://localhost:8800/builder): drop a photo on it (or on the picture) and it becomes a trial scene,
dusk and night made from it, the lights on a sphere found if that box is ticked; each trial a card
(its day, dusk and night) to show, keep in the app, or delete. Its layout: drag the countdown's outline or
the horizon on the picture (or type them), the countdown's size (40% to 130%) and three digits' size, and "See it with 3 digits" (150 days
before the trip); for any countdown app, a photo's scene or not. Its effects, for the scene showing:
lights on a sphere (found, a circle given, or removed; the show's patterns and how long each; one
held to watch; erasing and adding lights on the picture), and On the device: Install on the device
(tools/board/deploy.py over USB: the app's kept scene with the system and runtime it runs on, then the
app that runs; Signed asks for the key's passphrase then, in a dialog, and keeps it nowhere), window lights (found automatically in the
photo, dark windows in a plain wall or lit ones at dusk, a guess to touch up; or painted on the picture,
brush or box, or erased; the light's colour), water (found automatically, a guess, or painted on the
picture: it ripples, gentle to choppy, slow to fast; the cruise's sea stays its own), fireworks. The same from the command line:
`python3 tools/themegen/photo_scene.py PHOTO epcot --try --orb auto`; `--list epcot`, `--keep NAME
epcot`, `--back epcot` ([countdown apps](countdown.md#scenes)). `--browser` (or no `swiftc`) shows the same in a page at
http://localhost:8800. Settings > Apps opens the real app
picker. Each app keeps its own settings and data in `build/preview/data/`. The chess clock's DejaVu
fonts are copied once from the board's build tree (`tools/build/build.sh` first, or `FBCLOCK_FONTS`).

## Talking to the board — `tools/board/`

They use the board's shell over a serial line: the board's own micro-USB port plugged into the Mac
when it is (Linux's USB serial gadget: by far the fastest, and picked by itself), otherwise a 3.3 V
USB-serial adapter on the Nano's UART0 (115200 baud). Both give a root shell straight away (no password: physical access is the trust). `CLOCK_SERIAL` picks a
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
a local Stable Diffusion detail pass), the pre-drawn text (`build_ui.py`); `photo_scene.py PHOTO APP` (an app's whole scene from one
daytime photo) and `scene_pack.py WORK OUT` (any scene's pictures: day, dusk, night, mask, windows,
twinkle lights, into what the device loads): [countdown apps](countdown.md#scenes). Its
[README](../tools/themegen/README.md); and the castle's `tools/themegen/castle/build_castle.sh`.

## Apps — `tools/apps/`

`layout.py NAME [DEST]` (an app's files as they go on the board: the one rule the image, deploy and
packing share), `pack.py NAME [--key KEY]` (its tarball and signed statement, for `modinstall`),
`publish.py NAME ...` (pack, sign, and publish to the catalog on GitHub Releases), `keygen.sh` (the
signing key, once), and `new.py ID --name NAME [--park PARK]` (a new countdown app, running at once on
a placeholder scene: [countdown apps](countdown.md)): [apps](apps.md).

## WiFi — `tools/wifi/`

The ESP32's firmware: [wifi](wifi.md).

## The apps' own

`apps/chess/tools/simulate.py` (the clock's animations and touch handling against an in-memory screen)
and `apps/chess/tools/check_games.py` (every game in `apps/chess/games.pgn` replays: run it after adding one).
