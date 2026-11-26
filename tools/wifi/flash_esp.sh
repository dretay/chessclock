#!/bin/sh
# Flash the firmware build_esp_firmware.sh made onto the ESP32 over its own USB port.
#   tools/wifi/flash_esp.sh [esp32|esp32c3] [PORT] [--wiretest]   (PORT default: the one USB serial port that
#                                                                  isn't the Nano's; --wiretest: the wiring test)
# esptool comes through uv (uvx: fetched once, kept apart from the project's .venv); the port is found
# with the project's Python (pyserial). Run it from the project folder.
set -e
unset VIRTUAL_ENV                                    # (another project's, active in this terminal: not this one's)
REPO=$(cd "$(dirname "$0")/../.." && pwd)
TARGET=${1:-esp32}
KIND=$TARGET; for a in "$@"; do [ "$a" = "--wiretest" ] && KIND=wiretest-$TARGET; done
set -- $(for a in "$@"; do [ "$a" = "--wiretest" ] || echo "$a"; done)
OUT=$(cd "$(dirname "$0")" && pwd)/out/$KIND
WT=""; [ "$KIND" = "$TARGET" ] || WT=" --wiretest"
[ -f "$OUT/flash_args" ] || { echo "no $KIND firmware built: tools/wifi/build_esp_firmware.sh $TARGET$WT"; exit 1; }
# the ESP32's own USB serial port: any USB serial port but the Nano's own (its USB gadget, 0525:a4a7;
# a CP2102 on the Nano's console can share the ESP board's name, /dev/cu.usbserial-0001, so names
# don't tell them apart). Set CLOCK_SERIAL to leave out a console adapter too.
if [ -z "$2" ]; then
    PORTS=$(cd "$REPO" && uv run -q python -c '
import os
from serial.tools import list_ports
skip = os.environ.get("CLOCK_SERIAL", "")
for p in list_ports.comports():
    if p.device.startswith("/dev/cu.") and p.vid and (p.vid, p.pid) != (0x0525, 0xA4A7) and p.device != skip: print(p.device)' 2>/dev/null || true)
    [ "$(echo "$PORTS" | grep -c .)" = 1 ] || { echo "can't tell which port is the ESP32 (found: ${PORTS:-none}); name it: $0 $TARGET PORT"; exit 1; }
    PORT=$PORTS
else PORT=$2; fi
echo "flashing the $KIND firmware through $PORT"
cd "$OUT" && uvx esptool --chip "$TARGET" -p "$PORT" -b 460800 write-flash $(cat flash_args | tr '\n' ' ')
