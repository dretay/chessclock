# How the system works

**The SD card**: a base system and, on a partition of their own, the apps ([apps](apps.md)). The
base is a minimal Linux built with [Buildroot](https://buildroot.org) as a `BR2_EXTERNAL` tree
(Buildroot itself unmodified): `configs/licheepi_nano_defconfig`, `board/licheepi_nano/`,
`package/`.

**Kernel.** Mainline Linux 6.18 LTS. Mainline supports most of the F1C100s (SD card, DMA, I2C, PWM,
watchdog, audio, USB) but not its display, so [a patch](../board/licheepi_nano/linux/patches) adds
that, carried over from the [5.11 kernel fork](https://github.com/unframework/linux/commits/nano-5.11)
this project started on; another fixes the SPI controller's sampling (see [WiFi](wifi.md)). The
kernel config is cut down to what the apps use (no networking unless built with WiFi, no text
console, compiled for size), which leaves several megabytes more RAM than the old kernel did;
`STRICT_KERNEL_RWX` is off (it padded the kernel's sections to 1 MB each).

**Device tree.** The [custom device tree](../board/licheepi_nano/linux/suniv-f1c100s-licheepi-nano-custom.dts)
builds on mainline's Lichee Pi Nano file and adds:

* the display pipeline and the 800x480 panel;
* a dimmable backlight: the backlight driver's enable pin (PE6) driven by PWM at 500 Hz;
* the I2C bus to the Nano's on-board NS2009 resistive-touch chip (PE11/PE12), with the pins'
  internal pull-ups on, since the board has none and the bus doesn't work without them;
* the micro-USB port as a USB device (a serial console for the development tools);
* the ESP32 on SPI1, for WiFi ([wifi](wifi.md)).

**Boot.** U-Boot is [a v2021.01 fork](https://github.com/unframework/u-boot/commits/2021.01-f1c100s)
with F1C100s support, set up ([`uboot.fragment`](../board/licheepi_nano/uboot.fragment)) to boot
without its usual 2-second countdown or a USB scan, and without checking for a key press on the
serial console (a serial adapter left wired to the board but unplugged makes noise that reads as
one, and the board stopped at U-Boot's prompt with a white screen). The kernel is LZ4-compressed,
which unpacks faster than gzip on this CPU, and boots `quiet`. The screen shows nothing until the
first startup script (`S00app`) puts up the current app's splash image, ready-made in the screen's
pixel format, using only shell built-ins (starting programs is slow on this CPU).

**The CPU clock** is 600 MHz, set at the start of boot by `S00app` (the F1C100s's own is 408 MHz;
600 ran cleanly in testing, and the countdown's log reports a `self-check` once a minute). For
another speed, put its MHz (a multiple of 24) in `/apps/data/cpu_mhz`; `setcpu MHZ` changes it until
the next reboot, and `devmem 0x01C20000` shows it (24 MHz x (bits 8-12, plus 1)).

**The apps** run as `/etc/init.d/S99app` starts them (`run`, restarted if it exits; and an
optional background `service`): [apps](apps.md).

**Memory.** The F1C100s has 32 MB, about 26 MB of it free for programs: the apps draw straight into
the framebuffer, never holding more of a screen than they must (the countdown runtime's drawing is
a small C library, `apps/countdown/fx/vacfx.c`, called from Python). With WiFi too, it takes swap: a 32 MB
file on the apps partition (`/etc/init.d/S01swap`), used only under pressure ([wifi](wifi.md)). The
F1C200s (64 MB) is the protoboard's.

**USB power.** With the board's micro-USB port plugged into a computer, that also powers the board:
switching a bench supply off no longer resets it. A cable or adapter without the 5 V wire avoids it.
