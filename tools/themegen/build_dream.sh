#!/bin/bash
# Rebuild the Disney Dream theme from its sources:
#   1. the photo livery (dream/build_livery.py)       assets/dream  -> work/dream/livery
#   2. the Blender plates, double size (dream/scene.py)                -> work/dream/renders
#   3. the panel-A window mask, the Blender plates at 800x480, the mockup page and a preview sheet
#                                                                      -> vacation/themes/dream-blender, work/dream/mockup
#   4. the device theme from the photo (dream/photo_theme.py)          -> vacation/themes/dream
# Needs Blender (BLENDER=..., default the macOS app), Python 3 with Pillow, and the
# source files in assets/ (see vacation/themes/dream/SOURCES.md). Takes ~15 min on an M2.
#
#   tools/themegen/build_dream.sh            everything
#   tools/themegen/build_dream.sh --quick    48 samples at panel size: a quick look, ~3 min
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
export THEME_ASSETS="${THEME_ASSETS:-$REPO/assets/dream}"
export THEME_WORK="${THEME_WORK:-$HERE/work/dream}"
export HDRI_DIR="${HDRI_DIR:-$REPO/assets/hdri}"
REN="$THEME_WORK/renders"
SAMPLES=128; SCALE=2
[ "$1" = "--quick" ] && { SAMPLES=48; SCALE=1; }

for f in "$THEME_ASSETS/disney_dream.stl" "$THEME_ASSETS/side.png" "$THEME_ASSETS/bow.jpg" "$THEME_ASSETS/panel_photo.jpg"; do
  [ -f "$f" ] || { echo "missing $f (see vacation/themes/dream/SOURCES.md)"; exit 1; }
done
mkdir -p "$REN"

render() {   # render OUT_DIR LOOK [camera options...]
  local out="$1" look="$2"; shift 2
  "$BLENDER" -b -P "$HERE/dream/scene.py" -- --out "$out" --look "$look" --samples $SAMPLES --res-scale $SCALE "$@" 2>&1 \
    | grep -E "Error|Traceback" || true
  [ -f "$out/$look.png" ] || { echo "render failed: $look"; exit 1; }
}

echo "livery..."; python3 "$HERE/dream/build_livery.py" >/dev/null
for L in day dusk night_dark night_lit mask; do echo "render $L..."; render "$REN" $L; done
echo "close-ups..."
render "$REN/bow" day --az 62 --el 8 --dist 330 --lens 50 --shift 0.05 && mv "$REN/bow/day.png" "$REN/closeup_bow.png"
render "$REN/boats" day --az 30 --el 7 --dist 150 --lens 50 --shift 0 --target -20,-22,15 && mv "$REN/boats/day.png" "$REN/closeup_boats.png"
echo "page..."
python3 "$HERE/mockup/photo_windows.py"
python3 "$HERE/mockup/build_page.py"
echo "device theme (the photo version)..."
python3 "$HERE/dream/photo_theme.py"
