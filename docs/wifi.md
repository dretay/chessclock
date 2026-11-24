# WiFi

The Nano has no radio of its own: WiFi comes from an **ESP32 on its SPI bus**, running Espressif's
[ESP-Hosted-NG](https://github.com/espressif/esp-hosted-linux) firmware, so Linux sees an ordinary
`wlan0`. Used by the countdown apps (AIS ship positions, ride wait times) and for
network time. There's no ssh: the board is reached only over USB and its serial console.

**Memory:** WiFi costs about 4 MB of the Nano's 32 MB (the network stack and `cfg80211` built into the
kernel, and the driver's buffers, none of it given back), and a countdown app's own process about
11 MB. They fit together with swap (`S01swap`): first compressed memory (zram, LZ4: idle memory
compresses about 3:1 and comes back far faster than from the card), then a 32 MB file on the apps
partition (`/apps/swapfile`) if that fills; and the fetchers are small (the cruise's AIS is `aisd`, in
C: about 2 MB) or run briefly and exit (the castle's ride waits). The F1C200s (64 MB) on the protoboard ([hardware/protoboard](../hardware/protoboard)) needs
none of that. The kernel without WiFi is a separate build.

## Building and flashing

```sh
tools/build/build.sh --wifi --app castle       # -> build/images-wifi/ (its own build tree)
tools/board/flash_sd.sh build/images-wifi       # kernel and base system; the apps stay
```

The WiFi build adds `package/esp-hosted` (the `esp32_spi` driver, `S35wifi`, wpa_supplicant), the
kernel options in `board/licheepi_nano/linux/wifi.fragment`, and TLS for Python (OpenSSL, the CA
certificates). Only the kernel differs between the two builds in a way that matters for memory, and
it can be swapped on its own over USB (copy `zImage` to the boot partition, `/dev/mmcblk0p1`).

**The ESP32's firmware** is built in Espressif's ESP-IDF container and flashed over the ESP board's
own USB port:

```sh
tools/wifi/build_esp_firmware.sh esp32         # (or esp32c3) -> tools/wifi/out/esp32/
tools/wifi/flash_esp.sh esp32                  # finds the ESP's port (any USB serial but the Nano's)
```

Its settings are in `tools/wifi/sdkconfig.nano` (SPI mode 2; handshake and data-ready pins; no
Bluetooth). The firmware version must match the driver's (`ESP_HOSTED_VERSION` in
`package/esp-hosted/esp-hosted.mk`; the build script checks out the same commit).

## Wiring (ESP32 D1 mini / MiniKit; see the device tree)

| Nano | | ESP32 | |
|---|---|---|---|
| PA0 | SPI1 CS (pull-up: the pin's internal one, or 10 k to 3.3 V) | IO15 | |
| PA1 | SPI1 MOSI | IO13 | |
| PA2 | SPI1 CLK | IO14 | |
| PA3 | SPI1 MISO | IO12 | |
| PE9 | handshake (interrupt) | IO2 | |
| PE10 | data ready (interrupt) | IO4 | |
| PE2 | reset | EN (the board's RST) | |
| GND | | GND | **essential**: a ground wire straight between the two boards |

The device tree (`board/licheepi_nano/linux/suniv-f1c100s-licheepi-nano-custom.dts`) names these for
the driver (`reset-gpios`, `handshake-gpios`, `data-ready-gpios`, `spi-max-frequency`).

## On the board

`S35wifi` starts it all in the background (`/var/log/wifi.log`): the driver, then wpa_supplicant,
DHCP and network time. Networks are saved in `/apps/data/wifi/wpa_supplicant.conf` (on the apps
partition, so flashing a new base system keeps them). To add one without typing
the password into anything that logs it:

```sh
wpa_cli -i wlan0 add_network                   # prints a number, say 0
wpa_cli -i wlan0 set_network 0 ssid '"My Network"'
read -s P; wpa_cli -i wlan0 set_network 0 psk "\"$P\""; unset P
wpa_cli -i wlan0 enable_network 0; wpa_cli -i wlan0 save_config
```

(or a countdown app's Settings > WiFi, on the touchscreen).

## What it took (if WiFi misbehaves, check these first)

- **Everything received was shifted by one bit** (`Drop invalid pkt: len=98 offset=280`, a header of
  49/12 shifted left). The Nano's SPI controller samples late unless told otherwise: on the sun8i-H3
  style controller (which the F1C100s's is) mainline Linux never sets the sample mode, and its reset
  default is the delayed mode meant for 24-40 MHz. Fixed by
  `board/licheepi_nano/linux/patches/0002-spi-sun6i-use-normal-sample-mode-at-low-clock-rates.patch`.
  Found with a logic analyser: MISO read on the falling edge gave the right header, on the rising
  edge exactly the wrong one.
- **Replies got lost** (command timeouts, a reply arriving one command late). The ESP ends a
  transaction at its last byte, and the Nano can take 50 µs to milliseconds more to release CS; an
  ESP that had armed its next reply meanwhile counted that late CS edge as a finished (empty)
  transaction. Fixed in the firmware: `CONFIG_ESP_SPI_DEASSERT_HS_ON_CS=y` (`sdkconfig.nano`).
- **Scans failed** (`Scan trigger failed: ret=-22`): the driver told cfg80211 it takes no extra scan
  data, and wpa_supplicant always adds some. Fixed by
  `package/esp-hosted/0001-host-accept-and-ignore-scan-IEs.patch`.
- **The Nano couldn't reset the ESP** (EN stuck at 1.3 V): the D1 mini's USB auto-reset transistors
  fight any other driver of EN while its USB is connected. Power the ESP from a bench supply (USB
  unplugged) when the Nano drives its reset; flash it with USB connected, bench supply off. The
  protoboard's ESP32-C3 SuperMini has no such circuit (and no EN pin: reset by its load switch, or a
  bodge wire to its RST button).
- The driver's own reset pulse is 0.2-0.5 ms: enough for EN, far too short to power-cycle the ESP
  through a load switch (its capacitors keep it up); that would need a longer pulse in the driver.
