#!/bin/sh -e
# After Buildroot has filled the root filesystem: a login prompt on the USB serial port too
# (/dev/ttyGS0, the micro-USB port as seen from the Mac; see linux/linux_defconfig), beside the
# one on UART0.
INITTAB="${TARGET_DIR}/etc/inittab"
grep -q ttyGS0 "${INITTAB}" || \
	sed -i '/GENERIC_SERIAL/a ttyGS0::respawn:/sbin/getty -L ttyGS0 0 vt100 # USB serial' "${INITTAB}"
grep -q ttyGS0 "${INITTAB}" || echo 'ttyGS0::respawn:/sbin/getty -L ttyGS0 0 vt100 # USB serial' >> "${INITTAB}"
if [ -f "${TARGET_DIR}/etc/securetty" ] && ! grep -q ttyGS0 "${TARGET_DIR}/etc/securetty"; then
	echo ttyGS0 >> "${TARGET_DIR}/etc/securetty"
fi
