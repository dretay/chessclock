#!/bin/bash
# Build the SD card image incrementally (macOS, Apple's `container`), in a build tree that stays
# between builds instead of in image layers: ~7 GB of disk per kind of build rather than the
# builder's 100+.
#
#   tools/build/build.sh [--wifi] [--app chess|castle|cruise] [--fresh]
#     --wifi    the WiFi build (ESP32 over SPI, TLS for Python); its own build tree
#     --app     the app that starts at first boot (default chess; `app NAME` switches later)
#     --fresh   start this kind of build over from the base image (e.g. after Buildroot misbehaves)
#
# -> build/images[-wifi]/ (sdcard.img, boot.vfat, rootfs.ext4, ...): flash with tools/board/flash_sd.sh.
#
# Needs the base image, licheepi-nano-mybase (README, "Building"). The whole Buildroot tree (its
# sources, .config, downloads and build output) lives in a container volume (licheepi-out,
# licheepi-out-wifi), not in a folder on the Mac: macOS folders are case-insensitive, and the
# kernel's source has files whose names differ only in case. It's mounted where the base image
# built it (/root/buildroot): Buildroot records its own path everywhere, and moves files between
# its config and its output, so they must be on one filesystem. The first build of each kind
# seeds it from the base image.
#
# Buildroot rebuilds what changed by itself, except a few things whose changes it can't see (a
# kernel patch, a config fragment): tools/build/buildroot-make.sh rebuilds those when their files change.
# `container volume rm licheepi-out licheepi-out-wifi` takes it all away.
set -e
cd "$(dirname "$0")/../.."
REPO=$(pwd)
WIFI=0 APP=chess FRESH=
while [ $# -gt 0 ]; do
	case "$1" in
		--wifi) WIFI=1 ;;
		--app) APP=$2; shift ;;
		--fresh) FRESH=1 ;;
		-h|--help) sed -n '2,22p' "$0"; exit 0 ;;
		*) echo "unknown option $1 (see --help)"; exit 1 ;;
	esac
	shift
done
[ -x "apps/$APP/run" ] || { echo "--app must be an app in apps/ (chess, castle, cruise)"; exit 1; }
BASE=${BASE_IMAGE:-licheepi-nano-mybase}
VOL=licheepi-out; IMAGES=build/images
[ "$WIFI" = 1 ] && VOL=licheepi-out-wifi && IMAGES=build/images-wifi
container image inspect "$BASE" >/dev/null 2>&1 || { echo "no $BASE image: build it first (README, Building)"; exit 1; }

have_vol() { container volume inspect "$1" >/dev/null 2>&1; }
[ -n "$FRESH" ] && have_vol "$VOL" && container volume rm "$VOL" >/dev/null && echo "removed $VOL"
have_vol "$VOL" || { container volume create -s 40G "$VOL" >/dev/null && echo "created volume $VOL"; }

# seed a new volume from the base image's own Buildroot tree (the volume would hide it where it is,
# so it's mounted elsewhere for this)
container run --rm -v "$VOL:/seed" "$BASE" /bin/sh -c '
	[ -d /seed/output/build ] || { echo "seeding the build tree from the base image (once, a minute or two)"; rsync -a /root/buildroot/ /seed/; }'

mkdir -p "$IMAGES"
# (the container's own files are the base image's: the toolchain is in the volume, seeded from it)
container run --rm --cpus "${BUILD_CPUS:-8}" --memory "${BUILD_MEMORY:-4g}" \
	-v "$VOL:/root/buildroot" \
	-v "$REPO:/root/licheepi-nano" -v "$REPO/$IMAGES:/images" \
	-e WIFI="$WIFI" -e DEFAULT_APP="$APP" \
	"$BASE" /bin/bash /root/licheepi-nano/tools/build/buildroot-make.sh
echo "images in $IMAGES/ (flash: tools/board/flash_sd.sh $IMAGES)"
