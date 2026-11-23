#!/bin/sh
# Flash the firmware build_esp_firmware.sh made onto the ESP32 over its own USB port.
#   tools/wifi/flash_esp.sh [esp32|esp32c3] [PORT]      (PORT default: the first /dev/cu.usbserial-* that isn't the Nano's)
# Needs esptool (pip install esptool).
set -e
TARGET=${1:-esp32}
OUT=$(cd "$(dirname "$0")" && pwd)/out/$TARGET
# the ESP32's own USB serial port: any but the Nano's console adapter (and SLAB_USBtoUART, the
# Silicon Labs driver's second name for that same CP2102)
if [ -z "$2" ]; then
    PORTS=$(ls /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.usbmodem* 2>/dev/null | grep -v "^${CLOCK_SERIAL:-/dev/cu.usbserial-0001}$" || true)
    [ "$(echo "$PORTS" | grep -c .)" = 1 ] || { echo "can't tell which port is the ESP32 (found: ${PORTS:-none}); name it: $0 $TARGET PORT"; exit 1; }
    PORT=$PORTS
else PORT=$2; fi
echo "flashing $TARGET firmware through $PORT"
cd "$OUT" && esptool --chip "$TARGET" -p "$PORT" -b 460800 write-flash $(cat flash_args | tr '\n' ' ')
