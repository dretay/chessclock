#!/bin/sh
# Lays out the vacation countdown as an app folder (see docs/apps.md): install.sh DEST
# CC: the board's C compiler (arm-linux-gcc from the Buildroot build), for the drawing library.
# Used by board/licheepi_nano/post-image.sh (the SD card image) and tools/deploy_app.py.
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
THEMES=${THEMES:-dream}
rm -rf "$DEST"
mkdir -p "$DEST/fx" "$DEST/ui" "$DEST/map"
${CC:-arm-linux-gcc} -O2 -Wall -shared -fPIC -o "$DEST/fx/libvacfx.so" "$SRC/fx/vacfx.c" -lz
cp "$SRC"/vacation.py "$SRC"/vacation_*.py "$SRC/ais.py" "$SRC/vacation.conf" "$SRC/ships_example.csv" "$DEST/"
cp "$SRC/run" "$SRC/service" "$DEST/" && chmod 755 "$DEST/run" "$DEST/service"
cp "$SRC/ui/ui.bin.gz" "$SRC/fonts/OFL.txt" "$DEST/ui/"
cp "$SRC/map/map.json" "$DEST/map/" && cp -R "$SRC/map/tiles" "$DEST/map/tiles"
for t in $THEMES; do
	mkdir -p "$DEST/themes/$t"
	cp "$SRC/themes/$t"/*.gz "$SRC/themes/$t/theme.json" "$DEST/themes/$t/"
done
