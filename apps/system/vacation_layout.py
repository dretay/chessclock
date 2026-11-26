"""Where everything goes on the Settings pages, and every piece of text they show.

Shared by tools/themegen/build_ui.py, which draws the text on a desktop (Cormorant Garamond),
and by vacation_settings.py, which places it on the board through the C library: the board
draws Settings without Pillow, so it opens at once.
"""
W, H = 800, 480

# fonts: name -> point size
FONTS = {"title": 46, "value": 42, "label": 30, "small": 19, "button": 30, "chip": 24, "ship": 20, "tiny": 14}

IVORY, GOLD, DIM, DARK = (244, 238, 222), (226, 190, 120), (170, 176, 190), (24, 22, 30)
PANEL_FILL, PANEL_ALPHA, PANEL_LINE_ALPHA = (8, 14, 30), 178, 34

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---- page 1: dates
PAGE1_ROWS = [("Sail date", 78, [("sm", 100), ("sd", 80), ("sy", 106)]),
              ("Today", 236, [("tm", 100), ("td", 80), ("ty", 106), None, ("hh", 80), ("mi", 80), ("ap", 84)])]
PAGE1_BUTTONS = {"cancel": (24, 404, 150, 458), "display": (162, 412, 274, 450), "fireworks": (282, 412, 394, 450),
                 "theme": (402, 412, 514, 450), "wifi": (522, 412, 634, 450), "save": (646, 404, 776, 458)}
PAGE1_APPS = (250, 22, 362, 60)        # Apps › (the app picker), beside the title, when it's installed
# page 1 in each mode: an app's (its trip date; Fireworks, Theme, Device) and the device's (today's date
# and time; Display, WiFi): Settings > Device › runs the device's (the system package's device.py)
PAGE1_ROWS_APP = [PAGE1_ROWS[0]]
PAGE1_ROWS_DEVICE = [("Today", 78, PAGE1_ROWS[1][2])]
PAGE1_BUTTONS_APP = {"cancel": (24, 404, 150, 458), "fireworks": (162, 412, 310, 450), "theme": (324, 412, 472, 450),
                     "device": (486, 412, 634, 450), "save": (646, 404, 776, 458)}
PAGE1_SPLITS_APP = [(156, "cancel"), (317, "fireworks"), (479, "theme"), (640, "device"), (9999, "save")]
PAGE1_BUTTONS_DEVICE = {"cancel": (24, 404, 150, 458), "display": (162, 412, 306, 450), "wifi": (318, 412, 462, 450),
                        "dev": (474, 412, 634, 450), "save": (646, 404, 776, 458)}
PAGE1_SPLITS_DEVICE = [(156, "cancel"), (312, "display"), (468, "wifi"), (640, "dev"), (9999, "save")]
PAGE1_SPLITS = [(156, "cancel"), (278, "display"), (398, "fireworks"), (518, "theme"), (640, "wifi"), (9999, "save")]   # bottom row, by x

# ---- page 6: display (the device's settings: every app's)
BRIGHT_DAY = [(25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]
BRIGHT_NIGHT = [(10, "10%"), (25, "25%"), (50, "50%"), (75, "75%")]
PAGE6_PANEL = (20, 74, 780, 262)
PAGE6_ROWS = [("Daytime", 92, BRIGHT_DAY), ("Night", 176, BRIGHT_NIGHT)]           # (label, chip top, choices)
PAGE6_BUTTONS = {"back": (36, 404, 236, 458), "touch": (300, 412, 500, 450), "save": (564, 404, 764, 458)}

# ---- page 2: fireworks
SCHEDULES = [("random", "Random"), ("show", "Nightly show"), ("both", "Both"), ("off", "Off")]
RATES = [(30, "Rare"), (15, "Normal"), (7, "Often")]           # minutes between random bursts, on average
PAGE2_PANEL_A = (20, 74, 780, 214)                              # schedule and random-burst chips
PAGE2_CHIP_ROWS = [("Schedule", 88, SCHEDULES), ("Random", 150, RATES)]
CHIP_X0, CHIP_W, CHIP_H, CHIP_GAP = 190, 136, 48, 10
PAGE2_ROW_B = ("Show time", 226, [("fh", 80), ("fm", 80), ("fa", 84)])
PAGE2_BUTTONS = {"back": (36, 404, 236, 458), "demo": (300, 412, 500, 450), "save": (564, 404, 764, 458)}

# ---- page 3: the theme's settings (the app's, from its app.json: the cruise's ship
# to follow, the castle's rides to show): a label, then its options as chips, a page at a time
PAGE3_PANEL = (20, 74, 780, 398)
PAGE3_LABEL_Y = 108                                             # the setting's label, and its note
PAGE3_GRID = (36, 122, 3, 6, 38, 8)                             # x0, y0, columns, rows, chip height, gap
PAGE3_BUTTONS = {"back": (36, 404, 236, 458), "prev": (290, 412, 370, 450), "next": (430, 412, 510, 450),
                 "save": (564, 404, 764, 458)}

# ---- page 4: WiFi (networks in range), and page 5: a keyboard for the password
WIFI_STATUS_Y = 104                                             # "Connected to ..." under the title
WIFI_PANEL = (20, 124, 780, 392)                                # the networks, a row each
WIFI_ROW_H, WIFI_ROWS = 52, 5
WIFI_WIRETEST = (582, 136, 766, 178)                             # (no ESP32: the wiring test, top right of the panel)
WIFI_BUTTONS = {"back": (36, 404, 236, 458), "rescan": (300, 412, 500, 450), "forget": (564, 412, 764, 450)}
KB_FIELD = (20, 70, 780, 128)                                   # the password as typed
KB_TOP, KB_KEY_H, KB_GAP, KB_X0, KB_X1 = 140, 56, 8, 20, 780
KB_BUTTONS = {"kb_cancel": (36, 410, 236, 464), "kb_join": (564, 410, 764, 464)}
# the keys: rows of (label, what it types / does, width in key units)
KB_LETTERS = [[(c, c, 1) for c in "qwertyuiop"], [(c, c, 1) for c in "asdfghjkl"],
              [("shift", "shift", 1.5)] + [(c, c, 1) for c in "zxcvbnm"] + [("del", "del", 1.5)],
              [("123", "symbols", 1.5), ("space", " ", 5), (".", ".", 1), ("-", "-", 1), ("_", "_", 1)]]
KB_SYMBOLS = [[(c, c, 1) for c in "1234567890"], [(c, c, 1) for c in "!@#$%^&*()"],
              [("=", "=", 1), ("+", "+", 1), ("/", "/", 1), ("?", "?", 1), (":", ":", 1), (";", ";", 1), ("'", "'", 1), ('"', '"', 1), ("del", "del", 1.5)],
              [("abc", "letters", 1.5), ("space", " ", 5), (",", ",", 1), ("~", "~", 1), ("<", "<", 1), (">", ">", 1)]]

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
    "title": ["Settings", "Fireworks", "Touch calibration", "Theme settings", "WiFi", "Apps", "Display", "Get apps", "Device"],
    "label": ["Sail date", "Today", "Schedule", "Random", "Show time", " days to go", " day to go",
              "Today's the day!", "Already sailed", "Saved", "No changes", "Calibrated",
              "Tap the centre of the cross (1 of 4)", "Tap the centre of the cross (2 of 4)",
              "Tap the centre of the cross (3 of 4)", "Tap the centre of the cross (4 of 4)",
              "That didn't look right: nothing changed", "Opening apps...", "Daytime", "Night", "Opening device settings..."],
    "small": ["date & time", "bursts", "nightly show", "back to the countdown", "Calibrate touch", "Fireworks ›",
              "Demo show", "Demo show on exit", "fireworks!",
              "Theme ›", "Nothing to set for this theme", "Apps ›", "one moment", "Device ›", "back to the app", "Display ›", "brightness", "every app shares these", "Developer: on", "Developer: off", "Get apps ›", "Install", "Update", "Installed",
              "WiFi ›", "Touch", "Rescan", "Forget network", "Scanning...", "Not connected", "Connecting to ",
              "Connected to ", "No WiFi hardware (is the ESP32 connected?)", "Check wiring", "Try again", "Wiring test", "Listening to the wires...", "Tap a network to join it",
              "open", "shift", "del", "123", "abc", "space", "Join", "Password for ", "Joining...",
              "Couldn't connect: check the password", "Saved on the board", "No networks found",
              "WiFi isn't running yet"],
    "button": ["Cancel", "Save", "‹ Back", "Join", "‹", "›"],
    "chip": [t for _, t in SCHEDULES] + [t for _, t in RATES] + sorted({t for _, t in BRIGHT_DAY + BRIGHT_NIGHT}),
    "value": MONTHS + ["AM", "PM"],
}
# ---- the fleet map (the runtime's ships/screen.py; the chart itself is tools/themegen/build_map.py)
FLEET = ["Magic", "Wonder", "Dream", "Fantasy", "Wish", "Treasure", "Destiny", "Adventure"]   # "Disney ..."
STRINGS["ship"] = FLEET
STRINGS["small"] += ["Positions from ", " min ago", " h ago", " days ago", "Positions just in", "Example positions",
                     "at sea", "No position reported yet", "Beyond the Caribbean map"] + ["Disney " + n for n in FLEET]
STRINGS["label"] += ["Disney " + n for n in FLEET] + ["Follow", "Rides"]
STRINGS["chip"] += FLEET
STRINGS["tiny"] = ["Imagery: NASA Blue Marble", "Imagery: NASA Black Marble"]
CHAR_FONTS = ["small", "label"]   # every printable character on its own too (port names, WiFi names, the keyboard)
EXTRA_CHARS = "\u00b0\u2032\u00b7"    # degree, minute, middle dot

DIGIT_FONTS = ["value", "label", "small"]    # these get 0-9 as single glyphs too
