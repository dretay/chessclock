#!/bin/sh
# Lays out the chess clock as an app folder (see docs/apps.md): install.sh DEST
# Used by tools/apps/layout.py (the SD card image, deploy, pack).
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
rm -rf "$DEST"
mkdir -p "$DEST/splash"
cp "$SRC/fbclock.py" "$SRC/games.pgn" "$SRC/fbclock.conf" "$SRC/app.json" "$SRC/icon.rgb.gz" "$DEST/"
cp "$SRC/run" "$SRC/splash.sh" "$DEST/" && chmod 755 "$DEST/run" "$DEST/splash.sh"
cp "$SRC"/splash/*.raw.gz "$DEST/splash/"
