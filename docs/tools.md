# Development tools

On a new Mac, `tools/setup.sh` sets up what git doesn't hold, and says what else is missing (safe to
run again: it only does what's missing). Python is the project's own, through [uv](https://docs.astral.sh/uv/)
(`brew install uv`): the version in `.python-version`, uv's copy of it rather than Homebrew's (a Homebrew
upgrade can't break the environments), with the tools' packages (`pyproject.toml`, pinned in `uv.lock`) in `.venv` and the AI's in
`tools/themegen/work/aienv`; an environment not made that way is made afresh:

```sh
tools/setup.sh            # Python (uv's), the tools' environment (.venv: pyproject.toml's packages at uv.lock's
                          # versions) and the card fonts (assets/fonts/: Google Fonts, OFL), then checks for
                          # cc, swiftc, Apple's container and gh
tools/setup.sh --ai       # also the Scene Builder's "find automatically" (PyTorch, transformers and the
                          # segmentation model: ~1 GB; without it, sky, water and windows go by colour)
uv run tools/preview/preview.py castle    # any tool: uv run, from anywhere in the project (it uses this
                                          # project's .venv, whatever virtualenv is active, and keeps it in step)
```

The tools below that run by themselves (`tools/preview/preview.py`, `tools/board/deploy.py`,
`tools/apps/publish.py`, `tools/test/check.py`...) start with `#!/usr/bin/env -S uv run -q python`: run
them as written, from anywhere in the project, and they use its `.venv`. The rest (`photo_scene.py`,
`new.py`...) take `uv run` in front.

The photos scenes were made from are yours and stay out of git (`assets/`); the scenes made from them
are in the apps, in git.

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

**Controls** works on this Mac's preview (**Local**) or, picked at its top, on the countdown running on
the device (**Remote: the device (USB)**): the time of day (or the device's own clock), stay on the scene,
fireworks, the nightly show, birds and the lights' pattern, over the board's USB console (no network:
`tools/preview/remote.py` writes `/tmp/countdown-live.json` on the board, in RAM, which the countdown
looks at a few times a second; about a tenth of a second a change). Back to Local, the device is put back
as it is on its own (its clock, its screens in turn, every pattern); a reboot forgets it too. In Remote, the device also follows the preview's app: picking Remote, or
switching app (the App menu, the Scene Builder's picker, New…, the in-app picker), runs `app NAME` on it
(now and at every boot), if that app is installed there. While it starts (a few seconds), the device shows that app's splash: its picture, "Starting" and the pulsing dots, as at boot (the board's `app NAME` does too, from the next base image). Editing lights
is Local only. The console is let go after a few idle seconds, so deploys still work.

**Controls** also has **Birds** (a few cross the sky now, whether or not the scene has them on; the
builder's Birds card has the same as "Some now"). A screen's **Show now** in the builder saves the list
first if it has changed (the app has only the screens its app.json has), then shows that one.
Painted windows are lit like real ones (`scene_pack.painted_light`): a soft edge, brighter in the
middle, each window its own lamp, and a glow on the stone round it. **Group** (drag a box over several windows: every window it touches switches on and off as one light, e.g. a lantern's panes or a building's floor; `group` boxes in `windows_edits.json`, kept as `window_groups.json`), **Behind** (drag a box round a lit lantern or window: the darkest of the three tones the box splits into on the day photo, its ironwork or frame, goes in front of the light; `behind` boxes in `windows_edits.json`) and a window's **Frame** brush (paint what stays dark in front of its light (a lantern's bars,
mullions, leading: `window_frame.png`, from the `frame` strokes and `behind` boxes; Undo takes one back)); the light shows between them and their glow is blocked too. While the Window lights card is open,
or a window is being painted, every window is lit and holds still (live.json `windows_hold`).

The **Scene Builder** panel (View › Scene Builder ⌘B; `tools/preview/builder.html`, in the window, or at
http://localhost:8800/builder). It's docked to the picture's right edge (it moves and resizes with it;
drag it away to float it, back against the edge to dock it again; View › Dock Scene Builder ⇧⌘B). The
picker at its top switches app (and **New…** beside it makes one: a name, what the day is called, optionally a park's ride waits and a place's weather; `tools/apps/new.py` underneath, then it's the app shown, a plain sky waiting for a photo): each app's kept scene and trials are just as they were left, so any
scene can be opened again and changed. Its sections and each effect fold (click the title; remembered;
a closed effect still says what's in it, e.g. "398 lights"). Drop a photo on it (or on the picture) and it becomes a trial scene,
dusk and night made from it, the lights on a sphere found in it if the Lights on a sphere card says to look for them in each new photo (remembered per app; on by itself for an app whose scene has a sphere); each trial a card
(its day, dusk and night) to show, keep in the app, or delete. Its layout: drag the countdown's outline or
the horizon on the picture (or type them), the cards' look (Parchment; Black split-flap, like the cruise's; Wood trail sign; Departure board: only the cards are drawn again. Their fonts are in the git-ignored `assets/fonts/`: Cormorant Garamond, and from Google Fonts (OFL) Arvo Bold for the wood and Barlow Condensed SemiBold for the board, from github.com/google/fonts `ofl/arvo/`, `ofl/barlowcondensed/`), the countdown's size (40% to 130%) and three digits' size, and "See it with 3 digits" (150 days
before the trip); for any countdown app, a photo's scene or not. Its effects, for the scene showing:
lights on a sphere (found, a circle given, or removed; the show's patterns and how long each; one
held to watch; erasing and adding lights on the picture), Screens (the app's screens in turn with the
countdown: add a type, its seconds and settings: a weather screen's place (type a name, Find, and pick the right one of the places it could mean: Open-Meteo's geocoding; saved only once it's checked, ✓), a wait-times screen's park (picked from ThemeParks.wiki's list, by destination; into app.json "park", with its example waits) and tonight's show, a ship map's ship (the app's SHIP and MAP_SHIP); a name that can't be found says so; reorder,
remove, Show now; Save writes them into the app's app.json), and On the device: Install on the device
(tools/board/deploy.py over USB: the app's kept scene with the system and runtime it runs on, then the
app that runs; Signed asks for the key's passphrase then, in a dialog, and keeps it nowhere), window lights (found automatically in the
photo, dark windows in a plain wall or lit ones at dusk, a guess to touch up; or painted on the picture,
brush or box, or erased; the light's colour), smoke (click where it rises from: a campfire, a chimney;
its size, wind, thickness), foam (click where the water churns: its size, which way it flows, how
much), birds (on or off), water (found automatically, a guess, or painted on the
picture: it ripples, gentle to choppy, slow to fast; the cruise's sea stays its own), fireworks. The same from the command line:
`uv run tools/themegen/photo_scene.py PHOTO epcot --try --orb auto`; `--list epcot`, `--keep NAME
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

Makes the countdown apps' scenes, pictures and Settings text on a desktop: every app's scene from a
photo (the Scene Builder, or `photo_scene.py PHOTO APP`: an app's whole scene from one daytime photo),
the cruise's Caribbean map, the pre-drawn text (`build_ui.py`) and `scene_pack.py WORK OUT` (any scene's pictures: day, dusk, night, mask, windows,
twinkle lights, into what the device loads): [countdown apps](countdown.md#scenes). Its
[README](../tools/themegen/README.md).

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
