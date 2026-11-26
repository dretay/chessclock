#!/bin/sh
# Lays out the system package as an app folder (/apps/system; see docs/apps.md): install.sh DEST
# CC: the board's C compiler (arm-linux-gcc from the Buildroot build), for the drawing library and the
# loading dots. Used by tools/apps/layout.py (the SD card image, deploy, pack).
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
rm -rf "$DEST"
mkdir -p "$DEST/fx" "$DEST/ui"
${CC:-arm-linux-gcc} -O2 -Wall -shared -fPIC -o "$DEST/fx/libvacfx.so" "$SRC/fx/vacfx.c" -lz
${CC:-arm-linux-gcc} -O2 -Wall -o "$DEST/splashanim" "$SRC/fx/splashanim.c" -lm     # (the loading dots)
${CC:-arm-linux-gcc} -O2 -Wall -o "$DEST/fbgrab" "$SRC/fx/fbgrab.c" -lz              # (the screen, for the Mac's Remote mirror)
# (and as a JPEG, much smaller, when the base system has libjpeg; the Mac tries it first)
${CC:-arm-linux-gcc} -O2 -Wall -DWITH_JPEG -o "$DEST/fbgrab-jpeg" "$SRC/fx/fbgrab.c" -lz -ljpeg 2>/dev/null || true
cp "$SRC"/*.py "$SRC/app.json" "$SRC/API" "$DEST/"
for f in pick device; do [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DEST/" && chmod 755 "$DEST/$f"; done
cp "$SRC/ui/ui.bin.gz" "$SRC/fonts/OFL.txt" "$DEST/ui/"
