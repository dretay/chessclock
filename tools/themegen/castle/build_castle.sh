#!/bin/bash
# Build the castle module's scene end to end, every picture and mask from the same camera (scene.py),
# so the window light and the fireworks mask always line up with the plates:
#   renders: day, dusk, night (the plates), windows (the glass), mask (not sky), keep (castle + lamps)
#   ai_detail.py --keep: photographic detail everywhere but the castle and lamps (skip: --no-ai)
#   castle_theme.py: the device's files, in vacation/modules/castle/scenes/magic-kingdom/
# Any scene.py options (after --) go to every render, e.g. -- --dist 150 --eye 3.
# Inputs in assets/castle/ (the STL) and assets/hdri/; Blender in /Applications; the AI pass needs
# tools/themegen/work/aienv (see ai_detail.py). ~10 min with the AI pass.
set -e
cd "$(dirname "$0")/../../.."
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
AI=1; [ "$1" = "--no-ai" ] && { AI=; shift; }
[ "$1" = "--" ] && shift
for look in day dusk night windows mask keep; do
	case $look in day|dusk|night) extra="--samples 64" ;; *) extra="--samples 16 --grass 1" ;; esac
	echo "rendering $look"
	"$BLENDER" -b -P tools/themegen/castle/scene.py -- --look $look $extra "$@" 2>&1 | grep -E "Error|Traceback|windows:" || true
done
if [ -n "$AI" ]; then
	echo "AI detail pass"
	tools/themegen/work/aienv/bin/python tools/themegen/castle/ai_detail.py --keep --strength 0.55 2>&1 | grep -E " in [0-9]+ s|Error" || true
	python3 tools/themegen/castle/castle_theme.py
else
	python3 tools/themegen/castle/castle_theme.py --no-ai
fi
