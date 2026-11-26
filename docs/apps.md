# Apps

The SD card holds a **base system** and, separately, the **apps** that run on it.

| Partition | Mounted at | What's on it | Made by |
|---|---|---|---|
| 1 (FAT, 8 MB) | — | U-Boot's boot script, kernel and device tree | Buildroot |
| 2 (ext4, 64 MB) | `/` | the base system: Linux, BusyBox, Python with Pillow, the app launcher, `modinstall` and the keys it trusts | Buildroot (`configs/`, `board/`, `package/`) |
| 3 (ext4, 128 MB) | `/apps` | the apps, their settings and logs, the swap file | `board/licheepi_nano/post-image.sh`, from `apps/` |

The base system knows nothing about any one app, so changing an app never means rebuilding the
image: `tools/board/deploy.py` puts it on the board, signed or not. The image comes with every app in
`apps/` on it, and one starts at boot; Settings > Apps (the app picker) switches.

| App | | |
|---|---|---|
| `castle` | [apps/castle](../apps/castle) | the Magic Kingdom countdown, with live ride waits ([countdown apps](countdown.md)) |
| `epcot` | [apps/epcot](../apps/epcot) | the EPCOT countdown, with live ride waits (placeholder scene for now) |
| `cruise` | [apps/cruise](../apps/cruise) | the Disney cruise countdown, with the fleet map (the ships from their itineraries; [countdown apps](countdown.md)) |
| `countdown` | [apps/countdown](../apps/countdown/README.md) | the runtime the countdown apps run on (never started by itself) |
| `system` | `apps/system` | what every app shares: the drawing library, Settings' pages, **Device settings** (date and time, display, touch, WiFi), the app picker and Get apps; the countdown runtime runs on it |

## On the board

```
/apps/current              the app that starts at boot (e.g. "castle")
/apps/NAME/                an app's files, as tools/apps/layout.py lays them out
/apps/NAME/app.json        what it is: id, name, version (and a runtime it needs)
/apps/NAME/run             starts it (an app without one, like the countdown runtime, isn't started)
/apps/NAME/splash.sh       shows its boot splash (optional)
/apps/NAME/service         a background job beside it (optional)
/apps/NAME/.signature      the signed statement it was installed with (signed installs only)
/apps/data/NAME/           its settings, saved state and log (APP_DATA)
```

| Command | |
|---|---|
| `app` | which app starts at boot, and which are installed |
| `app NAME` | switch: start NAME now, and at every boot from now on |
| `app stop`, `app start`, `app restart` | the current app (e.g. stop it to run something else on the screen) |
| `app log` | follow its log |
| `modinstall APP.tar.gz` | check a signed app and install it (below) |

**Device settings** (Settings > Device › in every app; `/apps/system/device`) are the device's, shared
by every app: today's date and time, Display (day and night brightness; Calibrate touch) and WiFi. An
app's own Settings keep only its own (a countdown's trip date, fireworks and theme).

**The app picker** (Settings > Apps in every app; `/apps/system/pick`) shows every installed app
that has a `run`, with its `icon.rgb.gz` and name; a tap does `app NAME`.

## What an app is

A folder in `apps/` with an `app.json` (`{"id": ..., "name": ..., "version": "1.2.0"}`; the id is
the folder's name) and a `run`. `tools/apps/layout.py` lays it out for the board: the app's own
`install.sh DEST` if it has one (the countdown runtime compiles its C there, with `$CC`, the board's
compiler), else the folder as it is, less its `tools/` (desktop helpers), Python caches, and what
app.json's `exclude` lists. The image, `deploy.py` and `pack.py` all use that one rule. Then:

* **`run`** is started by `/etc/init.d/S99app` in the app's folder, with `APP_DATA` set to
  `/apps/data/NAME` (created for it). Whatever it prints goes to `APP_DATA/NAME.log`; the previous
  run's log is kept as `NAME.log.1`. If it exits it's started again two seconds later. It should
  `exec` the program, so stopping it stops the program.
* **`service`**, if there is one, runs beside `run` for as long as the app is the current one,
  started the same way (in the app's folder, with `APP_DATA`, started again if it exits) but on its
  own: restarting one doesn't restart the other. Its output goes to `APP_DATA/service.log` (the
  previous one as `service.log.1`). For work the screen shouldn't wait on, such as fetching data the
  app then reads from `APP_DATA`. One that needs the network should sleep when the kernel has no
  WiFi (`[ -d /sys/class/ieee80211 ] || exec sleep 2147483647`).
* **`splash.sh`**, if there is one, is *sourced* (not run, to save starting a shell) by
  `/etc/init.d/S00app`, the first thing at boot, in the app's folder with `APP_DATA` set. Keep it
  to shell built-ins: every program it starts delays the splash by tens of milliseconds.
* **Settings and anything else the app writes** go in `APP_DATA`, never in its own folder, which
  an install replaces.
* Python files are pre-compiled when the image is built; after a deploy, Python compiles the
  changed ones itself the first time they're loaded.
* An app on a **runtime** (the countdown apps) names it in app.json (`"runtime": "countdown", "api":
  2`); a runtime has `"kind": "runtime"`, an `API` file with the app api it provides, and no `run`.

The base system provides Python 3.12 (with ctypes), Pillow, FreeType, the DejaVu fonts, zlib, and
`setcpu MHZ` (sets the CPU clock until the next reboot). An app that needs more from the base needs
an image rebuild once, for that.

## Putting an app on the board

```sh
tools/board/deploy.py castle                       # quick: the files that changed, unsigned
tools/board/deploy.py --use epcot epcot            # ... and make it the app that runs
tools/board/deploy.py --signed countdown castle    # packed, signed, installed by modinstall
```

Quick deploys are the developer's way in: an app copied like that has no `.signature`. Both stop the
app while copying (the board drops bytes when it's busy) and start it once at the end. Copying is
fastest with the board's micro-USB port plugged into the Mac, which the tools use by themselves when
it's there ([tools](tools.md)). Files removed from an app aren't removed from the board by a quick
deploy (a signed install replaces the whole folder).

## Signed apps

```sh
tools/apps/keygen.sh                               # once: the signing key (~/.config/licheepi-nano/), and its
                                                   #   public half into the base system's trusted keys
tools/apps/pack.py castle --key ~/.config/licheepi-nano/module-signing.pem
                                                   # -> build/packages/castle-1.0.0.tar.gz and .tar.gz.sig
```

**The tarball** holds exactly what `layout.py` lays out, with a `MANIFEST.json` of each file's
SHA-256, and is reproducible. **The `.sig`** is a short signed statement: the app's id, name, version
and api, the runtime it needs (or, for a runtime, the api it provides), the tarball's size and
SHA-512, the signing key's id, and an Ed25519 signature over those lines. `modinstall`
(`package/modinstall`, in the base system; Ed25519 from [Monocypher](https://monocypher.org)):

1. checks the statement's signature against the keys in `/etc/modules/trusted.keys`, which only a
   new base system changes;
2. checks the tarball's size and SHA-512 against the statement, before reading anything in it;
3. refuses an older version than the installed one (`--force` allows it); an app whose runtime isn't
   installed, or is older than its api; a runtime older than an installed signed app needs
   (`--force`); `data`, `current` and `swapfile` (what else is in `/apps`), and replacing a folder
   that isn't an app;
4. unpacks into `/apps/.staging-ID`: regular files and folders only, all under `ID/`, no `..`, no
   links, size-limited;
5. swaps it in with one rename, keeping the previous version as `/apps/.old-ID`, and records the
   statement as `ID/.signature`.

It needs a few KB of memory whatever the app's size. `tools/test/test_modinstall.py` tries good apps
and the ways to get a bad one in.

**What signing doesn't do:** an app is a program running as root. The signature proves who made it
and that it wasn't changed; it doesn't limit what it can do. That's the right trade while every app
is yours.

**Developer mode, or only signed apps:** Settings > Device › **Developer: on / off** (on by default).
On, any app runs; off, only signed ones. It's the same switch as `app lock` (off) and `app unlock` (on)
on the board's console, and takes effect when Device settings close (the app starts again then).
Device settings always open, whatever's signed, so developer mode can always be turned back on.

**Locking to signed apps** (developer mode off, or `app lock`: `/apps/data/locked`): from then on S99app starts
only an app whose `.signature` checks out against the trusted keys, and its runtime's
(`modinstall --verify-installed`), else the first one that does; the picker shows only those;
`deploy.py` without `--signed` refuses. `app unlock` undoes it; `app` lists which apps are signed.

## The catalog (Get apps)

```sh
brew install gh && gh auth login                 # once: the GitHub CLI
tools/apps/publish.py system countdown castle cruise
```

`publish.py` packs and signs each app, makes a GitHub release `ID-VERSION` with its tarball and
`.sig` on this repository (refusing a version that's already published: bump app.json's), and updates
the catalog: `catalog.json` (each app's latest version and where to get it), signed the way an app is
(`catalog.json.sig`), on the release `catalog`. On the board, with WiFi: Settings > Apps > **Get
apps ›** downloads the catalog, checks it with `modinstall` (signed by a trusted key, unchanged), and
lists each app with Install, Update or Installed; a tap downloads the app (its runtime first if it's
missing or too old) and installs it with `modinstall`, which checks it again. `CATALOG_URL` in
`/apps/data/device.conf` points elsewhere. `tools/test/test_catalog.py` runs it all against a local
server.

**Keys:** the private key never goes in the repository (`*.pem` is ignored); `trusted.keys` can hold
several, so a new key can be added in one base-system update and the old one removed in a later one.

## Generated art in the repository

A scene is generated (and reproducibly: the generators write gzip files without timestamps, so the
same pictures make the same files), and each regeneration adds megabytes to the history. So commit a
scene's files at milestones, when a version is to be kept, rather than every iteration; work in
progress stays in `tools/themegen/work/` (ignored). If the history grows too big, the scenes' `*.gz`
are what to move to Git LFS.

## Changing the base system

Rebuild the image ([building](building.md)), then write it to the card with
`tools/board/flash_sd.sh build/images` (macOS). By default that writes just the first two partitions,
the kernel and the base system, so the apps and their settings stay; `--uboot` adds U-Boot, and
`--all` writes the whole `sdcard.img`, which resets the apps and their settings to the image's
(needed the first time, or if the partition sizes ever change). It finds the card, shows it, and
asks first.
