# Apps

The SD card holds a **base system** and, separately, the **apps** that run on it.

| Partition | Mounted at | What's on it | Made by |
|---|---|---|---|
| 1 (FAT, 8 MB) | — | U-Boot's boot script, kernel and device tree | Buildroot |
| 2 (ext4, 64 MB) | `/` | the base system: Linux, BusyBox, Python with Pillow, the app launcher | Buildroot (`configs/`, `board/`) |
| 3 (ext4, 128 MB) | `/apps` | the apps, and their settings and logs | `board/licheepi_nano/post-image.sh`, from `clock/` and `vacation/` |

The base system knows nothing about any one app, so changing an app never means rebuilding the
image: `tools/board/deploy_app.py` copies it over. The image comes with every app on it, and one starts
at boot.

## On the board

```
/apps/current              the name of the app that starts at boot (e.g. "vacation")
/apps/NAME/                an app's files, as its install.sh lays them out
/apps/NAME/run             starts it (required)
/apps/NAME/splash.sh       shows its boot splash (optional)
/apps/NAME/service         a background job beside it (optional)
/apps/data/NAME/           its settings, saved state and log (APP_DATA)
```

| Command | |
|---|---|
| `app` | which app starts at boot, and which are installed |
| `app NAME` | switch: start NAME now, and at every boot from now on |
| `app stop`, `app start`, `app restart` | the current app (e.g. stop it to run something else on the screen) |
| `app log` | follow its log |

## What an app is

A folder in this repository with an `install.sh DEST` that lays the app out in `DEST`: copying
its files and compiling any C with `$CC` (the board's compiler). From then on:

* **`run`** is started by `/etc/init.d/S99app` in the app's folder, with `APP_DATA` set to
  `/apps/data/NAME` (created for it). Whatever it prints goes to `APP_DATA/NAME.log`; the previous
  run's log is kept as `NAME.log.1`. If it exits it's started again two seconds later. It should
  `exec` the program, so stopping it stops the program.
* **`service`**, if there is one, runs beside `run` for as long as the app is the current one,
  started the same way (in the app's folder, with `APP_DATA`, started again if it exits) but on its
  own: restarting one doesn't restart the other. Its output goes to `APP_DATA/service.log` (the
  previous one as `service.log.1`). For work the screen shouldn't wait on, such as fetching data the
  app then reads from `APP_DATA` (the vacation countdown's: whatever its active module fetches, such
  as the cruise's AIS ship positions; see [vacation/README.md](../vacation/README.md#modules)).
* **`splash.sh`**, if there is one, is *sourced* (not run, to save starting a shell) by
  `/etc/init.d/S00app`, the first thing at boot, in the app's folder with `APP_DATA` set. Keep it
  to shell built-ins: every program it starts delays the splash by tens of milliseconds.
* **Settings and anything else the app writes** go in `APP_DATA`, never in its own folder, which
  a deploy replaces. An app that ships default settings copies them into `APP_DATA` the first time
  (see `vacation/run`).
* Python files are pre-compiled when the image is built; after a deploy, Python compiles the
  changed ones itself the first time they're loaded.

The base system provides Python 3.11 (with ctypes), Pillow, FreeType, the DejaVu fonts, zlib, and
`setcpu MHZ` (sets the CPU clock until the next reboot). An app that needs more from the base needs
an image rebuild once, for that.

To add an app: give its folder an `install.sh` and a `run`, and add it to `APPS` in
`board/licheepi_nano/post-image.sh` and `tools/board/deploy_app.py`.

## Changing an app

```sh
tools/board/deploy_app.py vacation            # lay it out and copy the changed files to the board
tools/board/deploy_app.py --use chess         # ... and make it the app that runs
```

It compiles any C with the board's compiler, from `tools/build/build.sh`'s build tree (so build once
first; with Docker instead, the Dockerfile's toolchain image: its top comment has the command). Copying is fastest with the board's micro-USB
port plugged into the Mac, which the tools use by themselves when it's there (see
[tools](tools.md)); over UART0, `tools/board/fast_serial.py` first, then `CLOCK_BAUD=1562500`. Files removed from an app aren't removed from the board.

## Changing the base system

Rebuild the image ([building](building.md)), then write it to the card with
`tools/board/flash_sd.sh build/images` (macOS). By default that writes just the first two partitions, the
kernel and the base system, so the apps and their settings stay; `--uboot` adds U-Boot, and `--all`
writes the whole `sdcard.img`, which resets the apps and their settings to the image's (needed the
first time, or if the partition sizes ever change). It finds the card, shows it, and asks first.
