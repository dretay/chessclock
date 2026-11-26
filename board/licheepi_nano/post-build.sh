#!/bin/sh -e
# After Buildroot has filled the root filesystem:
# - the consoles: UART0 (ttyS0) and the micro-USB port as a USB serial port (ttyGS0: what the Mac sees,
#   see linux/linux_defconfig) each give a root shell straight away. Physical access is the trust: root
#   has no usable password (BR2_TARGET_ENABLE_ROOT_LOGIN off), there's no ssh, so nothing logs in over
#   the network.
INITTAB="${TARGET_DIR}/etc/inittab"
sed -i -e '/getty.*ttyS0/d' -e '/getty.*ttyGS0/d' -e '/console shell/d' "${INITTAB}"
sed -i '/^# Put a getty on the serial port/a ttyS0::respawn:-/bin/sh # console shell (UART0)\nttyGS0::respawn:-/bin/sh # console shell (USB serial)' "${INITTAB}"
grep -q 'ttyGS0.*console shell' "${INITTAB}" || printf 'ttyS0::respawn:-/bin/sh # console shell (UART0)\nttyGS0::respawn:-/bin/sh # console shell (USB serial)\n' >> "${INITTAB}"
# - the root filesystem is read-only (boot.cmd's "ro", and no remount): what used to be written to it lives
#   on the apps partition instead. The random seed: /apps/data/system/seedrng (S00app makes the folder).
# no cron daemon (busybox.fragment): its start script, left by an earlier build with BusyBox's crond on
rm -f "${TARGET_DIR}/etc/init.d/S50crond"

mkdir -p "${TARGET_DIR}/etc/default"
echo 'SEEDRNG_ARGS="--seed-dir=/apps/data/system/seedrng"' > "${TARGET_DIR}/etc/default/seedrng"
