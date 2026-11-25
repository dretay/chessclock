#!/bin/sh
# Lays out the countdown runtime as an app folder (/apps/countdown; see docs/apps.md): install.sh DEST
# (It runs on the system package, /apps/system: the drawing library, Settings, the picker.)
# Used by tools/apps/layout.py (the SD card image, deploy, pack).
set -e
[ -n "$1" ] || { echo "usage: $0 DEST" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=$1
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC/vacation.py" "$SRC/apps.py" "$SRC/countdown.conf" "$SRC/app.json" "$SRC/API" "$DEST/"
cp "$SRC/launch" "$DEST/" && chmod 755 "$DEST/launch"
mkdir "$DEST/parks"                                       # (the park apps' wait times: screen, fetcher, service)
cp "$SRC/parks/board.py" "$SRC/parks/waits.py" "$DEST/parks/"
cp "$SRC/parks/service" "$DEST/parks/" && chmod 755 "$DEST/parks/service"
