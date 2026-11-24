#!/bin/sh
#
# This countdown app's boot splash (tools/themegen/app_splash.py), shown as early as possible:
# /etc/init.d/S00app sources this (in this folder) before anything else starts, so the screen isn't
# black while the countdown starts. Shell built-ins only, apart from zcat: every program started
# here delays the splash.
#
FB=/sys/class/graphics/fb0
if [ -e /dev/fb0 ] && [ -d "$FB" ]; then
	read -r SIZE < "$FB/virtual_size"
	read -r BPP < "$FB/bits_per_pixel"
	read -r STRIDE < "$FB/stride"
	W=${SIZE%,*}; H=${SIZE#*,}
	IMG=splash/splash-${W}x${H}x${BPP}-0.raw.gz
	# the image is whole rows back to back, so the screen's rows must be too
	if [ -f "$IMG" ] && [ "$STRIDE" -eq $((W * BPP / 8)) ]; then
		zcat "$IMG" > /dev/fb0
		# the dots after "Starting", pulsing (the countdown runtime's splashanim) until the app draws
		if [ -x /apps/system/splashanim ] && [ -r splash/dots ]; then
			read -r DX DY < splash/dots
			/apps/system/splashanim "$DX" "$DY" </dev/null >/dev/null 2>&1 &
		fi
	fi
fi
