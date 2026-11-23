#!/bin/sh
#
# The chess clock's boot splash, shown as early as possible: /etc/init.d/S00app runs this (in this
# folder, with APP_DATA set) before anything else starts. The image is stored compressed, in the
# screen's own pixel format, named for the screen it suits (see splash_name() in fbclock.py), one
# per orientation.
#
# Only shell built-ins are used apart from zcat: starting each extra program costs tens of
# milliseconds on this CPU, and every one delays the splash.
#

CONF=$APP_DATA/fbclock.conf
[ -r "$CONF" ] || CONF=fbclock.conf

# the saved settings (the last line for a key wins)
DAY= NIGHT= ROT=
if [ -r "$CONF" ]; then
	while IFS='=' read -r KEY VALUE; do
		case "$KEY" in
			DAY_BRIGHTNESS) DAY=$VALUE ;;
			NIGHT_BRIGHTNESS) NIGHT=$VALUE ;;
			ROTATE) ROT=$VALUE ;;
		esac
	done < "$CONF"
fi

# start at the dimmer of the two saved brightness levels (the clock sets the right one once it
# knows whether it's day or night)
for BL in /sys/class/backlight/*; do
	if [ -e "$BL/max_brightness" ]; then
		P=${NIGHT:-100}
		[ -n "$DAY" ] && [ "$DAY" -lt "$P" ] && P=$DAY
		read -r MAX < "$BL/max_brightness"
		LEVEL=$((MAX * P * P / 10000))
		[ "$LEVEL" -lt 1 ] && LEVEL=1
		echo "$LEVEL" > "$BL/brightness"
		break
	fi
done

FB=/sys/class/graphics/fb0
if [ -e /dev/fb0 ] && [ -d "$FB" ]; then
	read -r SIZE < "$FB/virtual_size"
	read -r BPP < "$FB/bits_per_pixel"
	read -r STRIDE < "$FB/stride"
	W=${SIZE%,*}; H=${SIZE#*,}
	IMG=splash/splash-${W}x${H}x${BPP}-${ROT:-0}.raw.gz
	# the image is whole rows back to back, so the screen's rows must be too
	if [ -f "$IMG" ] && [ "$STRIDE" -eq $((W * BPP / 8)) ]; then
		zcat "$IMG" > /dev/fb0
	fi
fi
