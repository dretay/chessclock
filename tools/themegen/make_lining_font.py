"""Make a copy of Cormorant Garamond whose digits are lining figures (full height, as on flip-clock
cards) and fixed at the SemiBold weight. Pillow here has no libraqm, so it can't turn on the
font's 'lnum' feature itself: this points the digit characters at the lining glyphs instead.

    (fonttools: in .venv, by tools/setup.sh)
    python3 tools/themegen/make_lining_font.py
    -> assets/fonts/CormorantGaramond-SemiBold-Lining.ttf   (SIL Open Font License, like the original)
"""
import os
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SRC = os.path.join(REPO, "assets", "fonts", "CormorantGaramond[wght].ttf")
DST = os.path.join(REPO, "assets", "fonts", "CormorantGaramond-SemiBold-Lining.ttf")
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

f = instancer.instantiateVariableFont(TTFont(SRC), {"wght": 600})
order = set(f.getGlyphOrder())
for table in f["cmap"].tables:
    for code, name in list(table.cmap.items()):
        if name in DIGITS and name + ".lf" in order: table.cmap[code] = name + ".lf"
f.save(DST)
print("wrote", DST)
