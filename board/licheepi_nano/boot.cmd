# Boots one of the card's two root slots (A: partition 2, B: partition 4), each a whole system: the
# kernel and device tree in its /boot. U-Boot's environment (uboot.env on this partition) says which:
#   bootslot          the slot known to work (a, or b)
#   bootslot_try      a slot just installed (bootslot install), being tried
#   bootslot_tries    how many times it has been started; once it has run a minute, bootslot confirm
#                     makes it the one that works. Three starts without that: back to bootslot, and
#   bootslot_failed   says which slot didn't make it (bootslot status shows it).
# The environment is written only while a slot is being tried (and once, the first time). A hang
# restarts through the watchdog, a kernel panic through panic=5, and a slot that won't load through
# the reset at the end: each a start that counts.
if test -z "${bootslot}"; then setenv bootslot a; saveenv; fi
setenv boot_slot ${bootslot}
if test -n "${bootslot_try}"; then
	if test -z "${bootslot_tries}"; then setenv bootslot_tries 0; fi
	if test ${bootslot_tries} -lt 3; then
		setexpr bootslot_tries ${bootslot_tries} + 1
		setenv boot_slot ${bootslot_try}
	else
		setenv bootslot_failed ${bootslot_try}
		setenv bootslot_try
		setenv bootslot_tries
	fi
	saveenv
fi
if test "${boot_slot}" = "b"; then setenv boot_part 4; else setenv boot_part 2; fi
setenv bootargs console=ttyS0,115200 quiet panic=5 rootwait root=/dev/mmcblk0p${boot_part} ro bootslot=${boot_slot}
load mmc 0:${boot_part} 0x80C00000 /boot/suniv-f1c100s-licheepi-nano-custom.dtb && load mmc 0:${boot_part} 0x80008000 /boot/zImage && bootz 0x80008000 - 0x80C00000
reset
