#!/bin/sh
# A countdown app's background job (the runtime's, for any app whose screens fetch something: an app's
# own service is `exec ../countdown/screens.sh`): the fetchers its screens need (screens.py --plan: ride
# waits, the weather...), each run once when it's due, one at a time (each a Python for a few seconds:
# the countdown and WiFi leave little memory), as often as its type says; after a failure, a minute,
# doubling, up to 15; until there's network time, every half minute. Its own notes in /tmp (in memory,
# not on the card). With no WiFi in the kernel it just sleeps.
[ -d /sys/class/ieee80211 ] || [ -n "$APP_NETWORK" ] || exec sleep 2147483647   # (no WiFi: nothing to fetch with; APP_NETWORK: the previewer)
HERE=$(cd "$(dirname "$0")" && pwd)
PLAN=$(python3 -S "$HERE/screens.py" --plan)
[ -n "$PLAN" ] || exec sleep 2147483647                       # (no screens that fetch)
NOTES=${TMPDIR:-/tmp}/screens-$(basename "$(pwd)")
mkdir -p "$NOTES"
while true; do
	now=$(date +%s)
	echo "$PLAN" | while read -r name every path; do
		due=$(cat "$NOTES/$name.due" 2>/dev/null || echo 0)
		[ "$now" -ge "$due" ] || continue
		python3 -S -OO -u "$HERE/$path" --once
		rc=$?; now=$(date +%s)
		retry=$(cat "$NOTES/$name.retry" 2>/dev/null || echo 60)
		case $rc in
			0) echo $((now + every)) > "$NOTES/$name.due"; echo 60 > "$NOTES/$name.retry" ;;
			2) echo $((now + 30)) > "$NOTES/$name.due" ;;
			*) echo $((now + retry)) > "$NOTES/$name.due"; retry=$((retry * 2)); [ $retry -gt 900 ] && retry=900; echo $retry > "$NOTES/$name.retry" ;;
		esac
	done
	sleep 30
done
