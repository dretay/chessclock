"""Patch KiCad's Specctra DSN for Freerouting.

KiCad exports the In1 no-tracks rule area as a wire_keepout, which Freerouting
also applies to through-vias, so nothing could reach the GND plane. Drop it;
gen/freerouting.rules (passed with -dr) switches In1 off for routing instead,
which still lets vias pass through and connect to the plane.

usage: python3 dsn_patch.py <in.dsn>   (patched in place)
"""
import re
import sys

path = sys.argv[1]
t = open(path).read()
pat = r'\s*\(wire_keepout "[^"]*" \(polygon "In1\.Cu[^"]*"[^)]*\)\)'
n = len(re.findall(pat, t))
open(path, "w").write(re.sub(pat, "", t))
print("dsn patched: %d In1 wire keep-out(s) removed" % n)
