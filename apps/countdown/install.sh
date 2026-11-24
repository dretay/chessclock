#!/bin/sh
# Lays out the vacation countdown as an app folder (see docs/apps.md): install.sh DEST
# CC: the board's C compiler (arm-linux-gcc from the Buildroot build), for the drawing library.
# THEMES: extra scenes to install (a module's default scene, from its module.json, always is).
# Used by board/licheepi_nano/post-image.sh (the SD card image) and tools/board/deploy_app.py.
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
THEMES=${THEMES:-}
rm -rf "$DEST"
mkdir -p "$DEST/fx" "$DEST/ui" "$DEST/modules"
# the host: the countdown, Settings, the drawing library and the pre-drawn text
${CC:-arm-linux-gcc} -O2 -Wall -shared -fPIC -o "$DEST/fx/libvacfx.so" "$SRC/fx/vacfx.c" -lz
cp "$SRC"/vacation.py "$SRC"/vacation_*.py "$SRC/modules.py" "$SRC/vacation.conf" "$DEST/"
cp "$SRC/run" "$SRC/service" "$DEST/" && chmod 755 "$DEST/run" "$DEST/service"
cp "$SRC/ui/ui.bin.gz" "$SRC/fonts/OFL.txt" "$DEST/ui/"
# the modules (modules.py): each folder whole, except scenes other than its default and THEMES (and caches)
for m in "$SRC"/modules/*/; do
	m=${m%/}; name=$(basename "$m")
	[ -f "$m/module.json" ] || continue
	mkdir -p "$DEST/modules/$name"
	for f in "$m"/* "$m"/.[!.]*; do
		[ -e "$f" ] || continue
		case "$(basename "$f")" in scenes|tools|__pycache__) continue ;; esac      # (tools/: the module's desktop helpers)
		cp -R "$f" "$DEST/modules/$name/"
	done
	if [ -d "$m/scenes" ]; then
		default=$(sed -n 's/.*"default": *"\([^"]*\)".*/\1/p' "$m/module.json")
		for t in $default $THEMES; do
			[ -d "$m/scenes/$t" ] || continue
			mkdir -p "$DEST/modules/$name/scenes/$t"
			cp "$m/scenes/$t"/*.gz "$m/scenes/$t/theme.json" "$DEST/modules/$name/scenes/$t/"
		done
	fi
	[ -f "$DEST/modules/$name/service" ] && chmod 755 "$DEST/modules/$name/service"
	# (the map's desktop previews aren't for the board)
	rm -f "$DEST/modules/$name"/map/preview_*.png
done
