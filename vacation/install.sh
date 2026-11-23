#!/bin/sh
# Lays out the vacation countdown as an app folder (see docs/apps.md): install.sh DEST
# CC: the board's C compiler (arm-linux-gcc from the Buildroot build), for the drawing library.
# THEMES: which of a module's scenes to install (default dream; a module's other scenes are left out).
# Used by board/licheepi_nano/post-image.sh (the SD card image) and tools/deploy_app.py.
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
THEMES=${THEMES:-dream}
rm -rf "$DEST"
mkdir -p "$DEST/fx" "$DEST/ui" "$DEST/modules"
# the host: the countdown, Settings, the drawing library and the pre-drawn text
${CC:-arm-linux-gcc} -O2 -Wall -shared -fPIC -o "$DEST/fx/libvacfx.so" "$SRC/fx/vacfx.c" -lz
cp "$SRC"/vacation.py "$SRC"/vacation_*.py "$SRC/modules.py" "$SRC/vacation.conf" "$DEST/"
cp "$SRC/run" "$SRC/service" "$DEST/" && chmod 755 "$DEST/run" "$DEST/service"
cp "$SRC/ui/ui.bin.gz" "$SRC/fonts/OFL.txt" "$DEST/ui/"
# the modules (modules.py): each folder whole, except scenes not in THEMES (and Python caches)
for m in "$SRC"/modules/*/; do
	m=${m%/}; name=$(basename "$m")
	[ -f "$m/module.json" ] || continue
	mkdir -p "$DEST/modules/$name"
	for f in "$m"/* "$m"/.[!.]*; do
		[ -e "$f" ] || continue
		case "$(basename "$f")" in scenes|__pycache__) continue ;; esac
		cp -R "$f" "$DEST/modules/$name/"
	done
	if [ -d "$m/scenes" ]; then
		for t in $THEMES; do
			[ -d "$m/scenes/$t" ] || continue
			mkdir -p "$DEST/modules/$name/scenes/$t"
			cp "$m/scenes/$t"/*.gz "$m/scenes/$t/theme.json" "$DEST/modules/$name/scenes/$t/"
		done
	fi
	[ -f "$DEST/modules/$name/service" ] && chmod 755 "$DEST/modules/$name/service"
	# (the map's desktop previews aren't for the board)
	rm -f "$DEST/modules/$name"/map/preview_*.png
done
