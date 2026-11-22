#!/bin/sh
# Regenerate the KiCad project from design.py, then run ERC and DRC.
# Refuses to overwrite a routed protoboard.kicad_pcb unless FORCE=1.
set -e
cd "$(dirname "$0")"
if [ "$1" != "--sch-only" ] && grep -q "^\s*(segment" ../protoboard.kicad_pcb 2>/dev/null && [ -z "$FORCE" ]; then
  echo "protoboard.kicad_pcb is routed: not regenerating it (FORCE=1 to overwrite; --sch-only to skip)" >&2
  exit 1
fi
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
mkdir -p .cache
python3 make_lib.py
python3 gen_sch.py
cd ..
kicad-cli sch export netlist protoboard.kicad_sch -o gen/.cache/protoboard.net 2>/dev/null
if [ "$1" != "--sch-only" ]; then
  "$KPY" gen/gen_pcb.py gen/.cache/protoboard.net protoboard.kicad_pcb 2>&1 | grep -v "wxApp\|traits"
fi
kicad-cli sch erc protoboard.kicad_sch -o gen/.cache/erc.rpt 2>/dev/null | grep Found
kicad-cli pcb drc --schematic-parity protoboard.kicad_pcb -o gen/.cache/drc.rpt 2>/dev/null | grep -i "found\|violation\|unconnected" || true
