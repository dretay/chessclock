#!/bin/bash
# Write a build to the SD card (macOS). See docs/apps.md.
#
# usage: tools/board/flash_sd.sh [--all] [--uboot] DIST_DIR [/dev/diskN]
#   DIST_DIR   the build's output (with sdcard.img, boot.vfat, rootfs.ext4, ...)
#   (default)  the base system only: the kernel (partition 1) and the root filesystem (2), so the
#              apps and their settings (partition 3) stay as they are
#   --uboot    U-Boot too (needed when uboot.fragment or U-Boot itself changed)
#   --all      the whole sdcard.img: everything, the apps and their settings reset to the image's
#   /dev/diskN the card; by default the one external disk there is (it asks before writing)
set -e

all= uboot=
args=()
for a in "$@"; do
	case "$a" in
		--all) all=1 ;;
		--uboot) uboot=1 ;;
		-h|--help) sed -n '2,11p' "$0"; exit 0 ;;
		*) args+=("$a") ;;
	esac
done
DIST=${args[0]}
DISK=${args[1]}
[ -n "$DIST" ] || { sed -n '2,11p' "$0"; exit 1; }
for f in sdcard.img boot.vfat rootfs.ext4 u-boot-sunxi-with-spl.bin; do
	[ -f "$DIST/$f" ] || { echo "no $f in $DIST (is it a build's output folder?)"; exit 1; }
done

if [ -z "$DISK" ]; then
	disks=$(diskutil list external physical | sed -n 's|^\(/dev/disk[0-9]*\) .*|\1|p')
	n=$(echo "$disks" | grep -c . || true)
	if [ "$n" -ne 1 ]; then
		echo "found $n external disks${disks:+: $(echo $disks)}; say which is the card: $0 ... $DIST /dev/diskN"
		exit 1
	fi
	DISK=$disks
fi
case "$DISK" in /dev/disk[0-9]*) ;; *) echo "$DISK isn't a /dev/diskN"; exit 1 ;; esac
info() { diskutil info -plist "$1" | plutil -extract "$2" raw - 2>/dev/null; }
[ "$(info "$DISK" Internal)" = false ] || { echo "$DISK is an internal disk: not touching it"; exit 1; }
size=$(info "$DISK" TotalSize)
[ "$size" -lt $((300 * 1024 * 1024 * 1024)) ] || { echo "$DISK is $((size / 1024 / 1024 / 1024)) GB: too big to be the SD card?"; exit 1; }
R=/dev/r${DISK#/dev/}

if [ -z "$all" ]; then
	# writing partitions on their own: the card must already have this layout (flashed with --all once)
	for p in 1:boot.vfat 2:rootfs.ext4; do
		part=${DISK}s${p%%:*}
		have=$(info "$part" IOKitSize || echo 0)
		need=$(stat -L -f %z "$DIST/${p#*:}")
		if [ -z "$have" ] || [ "$have" -lt "$need" ]; then
			echo "$part is ${have:-missing} bytes, ${p#*:} needs $need: flash the whole image (--all) once"
			exit 1
		fi
	done
	[ -n "$(info "${DISK}s3" IOKitSize)" ] || { echo "the card has no apps partition: flash the whole image (--all) once"; exit 1; }
fi

echo "The card: $DISK, $(info "$DISK" MediaName), $((size / 1000 / 1000 / 1000)) GB"
diskutil list "$DISK" | tail -n +2
if [ -n "$all" ]; then
	echo "Write the WHOLE image (everything on the card, including the apps' settings, is replaced)."
else
	echo "Write the kernel (${DISK}s1) and the base system (${DISK}s2)${uboot:+, and U-Boot}; the apps (${DISK}s3) stay."
fi
read -r -p "Go ahead? [y/N] " ok
[ "$ok" = y ] || [ "$ok" = Y ] || { echo "nothing written"; exit 1; }

diskutil unmountDisk "$DISK" >/dev/null
if [ -n "$all" ]; then
	sudo dd if="$DIST/sdcard.img" of="$R" bs=4m status=progress
else
	# (sync: the last block padded with zeros to a whole 1k: the raw disk takes only whole blocks, and U-Boot's
	# size isn't a multiple of them; the padding falls in the gap before the first partition)
	[ -n "$uboot" ] && sudo dd if="$DIST/u-boot-sunxi-with-spl.bin" of="$R" bs=1k seek=8 conv=notrunc,sync
	# (unmounted again before each: writing to the whole disk makes macOS look at the card afresh, and it
	# mounts the FAT partition again, mid-flash: a write to a mounted partition fails part way)
	diskutil unmountDisk "$DISK" >/dev/null
	sudo dd if="$DIST/boot.vfat" of="${R}s1" bs=1m status=progress
	diskutil unmountDisk "$DISK" >/dev/null
	sudo dd if="$DIST/rootfs.ext4" of="${R}s2" bs=1m status=progress
fi
sync
diskutil eject "$DISK" >/dev/null && echo "done: the card can come out"
