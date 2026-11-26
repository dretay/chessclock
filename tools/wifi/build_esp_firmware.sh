#!/bin/sh
# Build the ESP-Hosted firmware for the Nano's WiFi ESP32, in Espressif's ESP-IDF container
# (no ESP-IDF install needed on the Mac).
#
#   tools/wifi/build_esp_firmware.sh [esp32|esp32c3]     (default esp32: the MH-ET LIVE MiniKit)
#   tools/wifi/build_esp_firmware.sh esp32 --wiretest    the wiring test instead (tools/wifi/wiretest/)
#
# -> tools/wifi/out/<target>/ (or out/wiretest-<target>/): the .bin files and flash_args, flashed with
# flash_esp.sh. The ESP-Hosted version matches package/esp-hosted-nano (the Linux driver): they must agree.
set -e
TARGET=${1:-esp32}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ "$2" = "--wiretest" ]; then                     # (the wiring test: its source in wiretest/, built in work/)
    WORK=$HERE/work/wiretest-$TARGET; OUT=$HERE/out/wiretest-$TARGET
    rm -rf "$WORK" && mkdir -p "$WORK" && cp -R "$HERE/wiretest/." "$WORK/"
    container run --rm --memory 4g --cpus 8 -v "$WORK:/project" -w /project espressif/idf:v6.1 sh -c "
        idf.py set-target $TARGET >/dev/null && idf.py build" | tail -6
    rm -rf "$OUT" && mkdir -p "$OUT" && cp "$WORK/build/flash_args" "$OUT/"
    for f in $(grep -o '[^ ]*\.bin' "$WORK/build/flash_args"); do mkdir -p "$OUT/$(dirname "$f")"; cp "$WORK/build/$f" "$OUT/$f"; done
    echo "wiring test firmware -> $OUT"; exit 0
fi
REPO=$(cd "$HERE/../.." && pwd)
VERSION=$(sed -n 's/^ESP_HOSTED_NANO_VERSION = //p' "$REPO/package/esp-hosted-nano/esp-hosted-nano.mk")
WORK=$HERE/work; OUT=$HERE/out/$TARGET
mkdir -p "$WORK" "$OUT"
if [ ! -d "$WORK/esp-hosted-linux" ]; then
    git clone -q https://github.com/espressif/esp-hosted-linux "$WORK/esp-hosted-linux"
fi
git -C "$WORK/esp-hosted-linux" fetch -q --depth 1 origin "$VERSION" 2>/dev/null || true
git -C "$WORK/esp-hosted-linux" checkout -q "$VERSION"
cp "$HERE/sdkconfig.nano" "$WORK/esp-hosted-linux/esp/esp_driver/network_adapter/sdkconfig.nano"
# (in the container: a fresh sdkconfig from the defaults plus ours, then build)
container run --rm --memory 4g --cpus 8 -v "$WORK/esp-hosted-linux:/project" -w /project/esp/esp_driver/network_adapter \
    espressif/idf:v6.1 sh -c "
        rm -rf build sdkconfig &&
        export SDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.$TARGET;sdkconfig.nano' &&
        idf.py set-target $TARGET >/dev/null && idf.py build" | tail -15
B=$WORK/esp-hosted-linux/esp/esp_driver/network_adapter/build
# everything flash_args names (offset, path in the build folder), keeping the paths
rm -rf "$OUT" && mkdir -p "$OUT" && cp "$B"/flash_args "$OUT"/
for f in $(grep -o '[^ ]*\.bin' "$B"/flash_args); do mkdir -p "$OUT/$(dirname "$f")"; cp "$B/$f" "$OUT/$f"; done
grep -E "CONFIG_ESP_SPI_HOST_INTERFACE|CONFIG_ESP_SPI_MODE|GPIO_HANDSHAKE|GPIO_DATA_READY|DEASSERT_HS_ON_CS|^CONFIG_BT_ENABLED" \
    "$WORK/esp-hosted-linux/esp/esp_driver/network_adapter/sdkconfig" > "$OUT/settings.txt" || true
echo "firmware -> $OUT"; cat "$OUT/settings.txt"
