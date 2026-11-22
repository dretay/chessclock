"""Where everything goes on the Settings pages, and every piece of text they show.

Shared by tools/themegen/build_ui.py, which draws the text on a desktop (Cormorant Garamond),
and by vacation_settings.py, which places it on the board through the C library: the board
draws Settings without Pillow, so it opens at once.
"""
W, H = 800, 480

# fonts: name -> point size
FONTS = {"title": 46, "value": 42, "label": 30, "small": 19, "button": 30, "chip": 24}

IVORY, GOLD, DIM, DARK = (244, 238, 222), (226, 190, 120), (170, 176, 190), (24, 22, 30)
PANEL_FILL, PANEL_ALPHA, PANEL_LINE_ALPHA = (8, 14, 30), 178, 34

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---- page 1: dates
PAGE1_ROWS = [("Sail date", 78, [("sm", 100), ("sd", 80), ("sy", 106)]),
              ("Today", 236, [("tm", 100), ("td", 80), ("ty", 106), None, ("hh", 80), ("mi", 80), ("ap", 84)])]
PAGE1_BUTTONS = {"cancel": (36, 404, 216, 458), "calibrate": (236, 412, 396, 450),
                 "fireworks": (404, 412, 564, 450), "save": (584, 404, 764, 458)}

# ---- page 2: fireworks
SCHEDULES = [("random", "Random"), ("show", "Nightly show"), ("both", "Both"), ("off", "Off")]
RATES = [(30, "Rare"), (15, "Normal"), (7, "Often")]           # minutes between random bursts, on average
PAGE2_PANEL_A = (20, 74, 780, 214)                              # schedule and random-burst chips
PAGE2_CHIP_ROWS = [("Schedule", 88, SCHEDULES), ("Random", 150, RATES)]
CHIP_X0, CHIP_W, CHIP_H, CHIP_GAP = 190, 136, 48, 10
PAGE2_ROW_B = ("Show time", 226, [("fh", 80), ("fm", 80), ("fa", 84)])
PAGE2_BUTTONS = {"back": (36, 404, 236, 458), "demo": (300, 412, 500, 450), "save": (564, 404, 764, 458)}

COL_X0, COL_GAP, SPLIT_GAP, COL_H = 182, 8, 22, 128


def columns(row_cols, top):
    """key -> (x0, top, x1) for a row of spinners."""
    out, x = {}, COL_X0
    for c in row_cols:
        if c is None: x += SPLIT_GAP; continue
        out[c[0]] = (x, top + 10, x + c[1]); x += c[1] + COL_GAP
    return out


# every fixed piece of text, by font (numbers are drawn digit by digit)
STRINGS = {
    "title": ["Settings", "Fireworks", "Touch calibration"],
    "label": ["Sail date", "Today", "Schedule", "Random", "Show time", " days to go", " day to go",
              "Today's the day!", "Already sailed", "Saved", "No changes", "Calibrated",
              "Tap the centre of the cross (1 of 4)", "Tap the centre of the cross (2 of 4)",
              "Tap the centre of the cross (3 of 4)", "Tap the centre of the cross (4 of 4)",
              "That didn't look right: nothing changed"],
    "small": ["date & time", "bursts", "nightly show", "back to the countdown", "Calibrate touch", "Fireworks ›",
              "Demo show", "Demo show on exit", "fireworks!"],
    "button": ["Cancel", "Save", "‹ Back"],
    "chip": [t for _, t in SCHEDULES] + [t for _, t in RATES],
    "value": MONTHS + ["AM", "PM"],
}
DIGIT_FONTS = ["value", "label"]          # these get 0-9 as single glyphs too
