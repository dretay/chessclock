"""Text for screens and Settings pages: drawing any string with the pre-drawn fonts (ui/ui.bin.gz, from
vacation_layout.py's STRINGS), and making text from data (ride names, places) drawable.

A string is drawn whole when it was pre-drawn in that font, else character by character: every
printable ASCII character exists on its own in the CHAR_FONTS ("small", "label"), digits in the
DIGIT_FONTS too, plus EXTRA_CHARS; anything else would show as "?". plain() turns typographic
punctuation and accented letters into those characters first.
"""
import unicodedata

import vacation_layout as L

SWAPS = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
         " ": " ", "™": "", "®": "", "©": ""}


def plain(s):
    """s with only characters the fonts have: quotes and dashes made ASCII, accents dropped."""
    s = "".join(SWAPS.get(ch, ch) for ch in str(s))
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if 32 <= ord(ch) < 127 or ch in L.EXTRA_CHARS)


def rgb(c): return (c[0] << 16) | (c[1] << 8) | c[2]


class Text:
    """Drawing text with the C library's vfx_ui_* (on whatever screen is open)."""

    def __init__(self, fx):
        self.fx, self.ids = fx, {}

    def sid(self, key):
        if key not in self.ids: self.ids[key] = self.fx.vfx_ui_find(key.encode())
        return self.ids[key]

    def parts(self, font, s, x):
        """[(glyph id, x)] and the width: the whole string if it was pre-drawn, else per character."""
        k = self.sid("%s|%s" % (font, s))
        if k >= 0: return [(k, x)], self.fx.vfx_ui_metric(k, 4)
        out = []; x0 = x
        for ch in s:
            kk = self.sid("%s|%s" % (font, ch))
            if kk < 0: kk = self.sid("%s|?" % font)
            out.append((kk, x)); x += self.fx.vfx_ui_metric(kk, 4)
        return out, x - x0

    def width(self, font, s): return self.parts(font, s, 0)[1]

    def fit(self, font, s, w):
        """s, shortened with "..." if it's wider than w."""
        if self.width(font, s) <= w: return s
        while s and self.width(font, s + "...") > w: s = s[:-1]
        return s.rstrip() + "..."

    def draw(self, font, s, x, base, color, align="l", alpha=255):
        """Draw s with its left (align "l"), right ("r") or middle ("m") at x; returns its width."""
        w = self.width(font, s)
        x = x - w if align == "r" else x - w // 2 if align == "m" else x
        for k, xx in self.parts(font, s, x)[0]: self.fx.vfx_ui_text(k, xx, base, rgb(color), alpha)
        return w
