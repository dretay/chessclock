#!/bin/sh
# Autoroute a board with Freerouting, then import, clean up, refill zones and run DRC.
#   FREEROUTING_JAR=/path/to/freerouting.jar [JAVA=/path/to/java] ./gen/route.sh [passes]
# (Freerouting 2.5 needs Java 25+)
# Options (env):
#   WORK=<dir>    directory holding the protoboard.kicad_pcb/.kicad_pro to route (default: the project)
#   RULES=<file>  Freerouting rules (default gen/freerouting.rules: In1 = GND plane, no tracks)
#   KEEP_TRACKS=1 continue from the existing tracks instead of a fresh route
# Overwrites the tracks in <WORK>/protoboard.kicad_pcb (placement is kept).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$ROOT}"
RULES="${RULES:-$ROOT/gen/freerouting.rules}"
B="$WORK/protoboard.kicad_pcb"
C="$WORK/.route"
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
JAR="${FREEROUTING_JAR:-$HOME/.local/share/freerouting/freerouting.jar}"
[ -f "$JAR" ] || { echo "Freerouting jar not found: set FREEROUTING_JAR (https://github.com/freerouting/freerouting/releases)"; exit 1; }
mkdir -p "$C"
F="grep -v wxApp\|traits\|swig\|Debug"
"$KPY" "$ROOT/gen/route.py" export "$B" "$C/protoboard.dsn" 2>&1 | $F
python3 "$ROOT/gen/dsn_patch.py" "$C/protoboard.dsn"
"${JAVA:-java}" -jar "$JAR" -de "$C/protoboard.dsn" -dr "$RULES" -do "$C/protoboard.ses" -mp "${1:-40}" --gui.enabled=false
"$KPY" "$ROOT/gen/route.py" import "$B" "$C/protoboard.ses" 2>&1 | $F
kicad-cli pcb drc --format json "$B" -o "$C/drc.json" >/dev/null 2>&1 || true
"$KPY" "$ROOT/gen/viafix.py" "$B" "$C/drc.json" +1V1 In2.Cu 2>&1 | grep "vias added"   # +1V1 into its In2 area
for i in 1 2; do   # a second round: removing a via can leave its neighbour dangling
  kicad-cli pcb drc --format json "$B" -o "$C/drc.json" >/dev/null 2>&1 || true
  "$KPY" "$ROOT/gen/route.py" clean "$B" "$C/drc.json" 2>&1 | grep "removed"
done
kicad-cli pcb drc --schematic-parity "$B" -o "$C/drc.rpt" 2>/dev/null | grep -i "found" || true
