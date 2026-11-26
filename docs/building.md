# Building and flashing

Builds run in containers: Apple's [`container`](https://github.com/apple/container) tool on macOS,
or Docker. Two steps: a slow one-off **base image** (the cross-compiler and a complete first
build, 1-2 hours), then **incremental builds** that take in your current files and rebuild what
changed (seconds to minutes).

## On macOS with Apple's `container`

```sh
# once: the base image, built natively for Apple silicon
container build --memory 4g --cpus 8 -f Dockerfile.base --target main -t licheepi-nano-mybase:latest .

# each time: an incremental build, into build/images/ (build/images-wifi/ with --wifi)
tools/build/build.sh [--wifi] [--app castle] [--fresh]
```

`tools/build/build.sh` keeps the whole Buildroot tree between builds in a container volume
(`licheepi-out`, `licheepi-out-wifi`; ~8 GB each), seeded from the base image the first time. A build
that changes nothing takes under half a minute. Buildroot rebuilds what changed by itself, except a
few things it can't see change; `tools/build/buildroot-make.sh` rebuilds those when their files do:
the kernel (its patches, config, device tree), BusyBox and U-Boot (their config fragments), the boot
script, the WiFi driver package, and Python (its TLS option). `--fresh` starts that kind of build
over from the base image; `container volume rm licheepi-out` frees its space.

The tree lives in a volume rather than a folder on the Mac because macOS folders are
case-insensitive and the kernel's source has files whose names differ only in case; and it's
mounted where the base image built it (`/root/buildroot`), as Buildroot records its own path
everywhere.

`--app` picks the app that starts at first boot (`chess` by default, `castle` or `cruise`); on the board,
`app NAME` (or Settings > Apps) switches later. Apps change without a new image at all: `tools/board/deploy.py`
([apps](apps.md)).

To look around inside: `container run -it -v licheepi-out:/root/buildroot licheepi-nano-mybase /bin/bash`
(then `cd /root/buildroot; make menuconfig`, say).

### Disk space

The volumes stay their size (~8 GB each). The **builder's cache** doesn't: the base image build leaves gigabytes of layers in it that the builder never gives back
to macOS (it reached 100+ GB here). After building with `container build`:

```sh
container builder stop && container builder delete     # frees the cache; the images stay
```

Not `container image prune --all`: that also deletes the base image (`licheepi-nano-mybase`), and
rebuilding it takes an hour or two.

## With Docker

The same two steps, with Docker in place of Apple's tool: `tools/build/build.sh` uses Docker when
`container` isn't installed (or `CONTAINER=docker` to choose it).

```sh
docker build -f Dockerfile.base --target main -t licheepi-nano-mybase:latest .
tools/build/build.sh [--wifi] [--app castle] [--fresh]
```

## Flashing the SD card

```sh
tools/board/flash_sd.sh build/images            # macOS: the kernel and base system; the apps stay
tools/board/flash_sd.sh --all build/images      # the whole card: apps and their settings reset too
tools/board/flash_sd.sh --uboot build/images    # ... and U-Boot (when uboot.fragment changed)
```

It finds the one external disk, refuses internal or very large ones, shows the card and asks first.
`--all` is needed the first time (or if the partition sizes change). Elsewhere: write
`build/images/sdcard.img` whole with `dd` (Linux, `/dev/sdX`) or Balena Etcher (Windows). If macOS
says the card isn't readable afterwards, click **Ignore**: it's Linux's.
