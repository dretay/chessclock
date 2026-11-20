#!/usr/bin/env python3
"""
Chess clock for the LicheePi Nano: a chessboard that replays famous games,
sliding one piece every few seconds, beside a walnut chess-clock case showing
the hour and minutes on two clock faces, with the pieces each side has lost
in a tray below. On the hour, a pawn marches up and promotes into the new
hour; each minute the case's plunger dips and the minute face flips over.
Tapping the (resistive) touchscreen opens Settings: the time, daytime and
night-time brightness, and turning the display upside down.

Rendering uses Pillow and writes raw pixels to /dev/fb0 (no X11/SDL). The
board only has 32MB of RAM, so the screen is never held as one full image:
board squares and the parts of the clock case are drawn and written
separately.

See clock/README.md in the repository for the settings file, logs, command
line options and how to try it on a desktop. In short:

Settings (/etc/fbclock.conf, KEY=VALUE): TOUCH_X_MIN, TOUCH_X_MAX,
TOUCH_Y_MIN, TOUCH_Y_MAX, TOUCH_SWAP_XY (touch calibration); ROTATE;
DAY_BRIGHTNESS, NIGHT_BRIGHTNESS (percent); NIGHT_START, NIGHT_END (HH:MM).

Environment overrides:
  FBCLOCK_DEVICE    framebuffer device (default /dev/fb0)
  FBCLOCK_TOUCH_BUS I2C bus with the NS2009 touch chip (default /dev/i2c-0)
  FBCLOCK_GAMES     PGN file (default /usr/share/fbclock/games.pgn)
  FBCLOCK_FONTS     extra directory to search for DejaVu fonts
  FBCLOCK_MOVE_SECS seconds between moves (default 3)
  FBCLOCK_PREVIEW   render one frame to this PNG and exit (for development),
                    sized FBCLOCK_SIZE (default 800x480), after FBCLOCK_PLY moves
  FBCLOCK_PREVIEW_SETTER  if set, preview the settings screen instead

Command line:
  fbclock.py --touch-debug                    print raw/screen touch positions
  fbclock.py --make-splash DIR WxHxBPP        write the boot splash images
"""

import fcntl
import gzip
import math
import mmap
import os
import random
import re
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

# ---------------------------------------------------------------- settings

GAMES_FILE = os.environ.get("FBCLOCK_GAMES", "/usr/share/fbclock/games.pgn")
SPLASH_DIR = "/usr/share/fbclock"   # boot splash images, see splash_name()
CONFIG_FILE = "/etc/fbclock.conf"
MOVE_SECS = float(os.environ.get("FBCLOCK_MOVE_SECS", "3"))
SLIDE_SECS = 0.8          # how long a piece takes to glide to its new square
START_HOLD_SECS = 4       # show the starting position this long
CAPTION_SECS = 12         # how long a new game's name stays on screen
END_HOLD_SECS = 20        # show the final position this long
SETTER_TIMEOUT = 60       # leave the settings screen after this long without a tap
MIN_BRIGHTNESS = 5        # percent; the sliders never go fully dark
# Daytime/night-time brightness (percent) and when night starts and ends are
# kept in CONFIG_FILE as DAY_BRIGHTNESS, NIGHT_BRIGHTNESS, NIGHT_START and
# NIGHT_END (HH:MM, 24-hour); these are the defaults.
DEFAULT_DAY, DEFAULT_NIGHT = 100, 30
DEFAULT_NIGHT_START, DEFAULT_NIGHT_END = "21:00", "07:00"
PROMOTE_SECS = (0.35, 0.9, 0.4, 0.45)   # hour change: old hour fades, pawn marches,
                                        # promotes to a queen, queen becomes the hour
PRESS_SECS = 0.12         # minute change: the plunger goes down, then up...
FLIP_SECS = 0.45          # ...while the minute face flips over like a split-flap
FLIP_FRAMES = 14          # frames are built in advance, then played back evenly

BG = (22, 19, 16)
ACCENT = (232, 182, 92)
CASE_WOOD = (92, 58, 34)             # the walnut chess-clock case
CASE_GRAIN = (98, 63, 38)
CASE_DARK = (40, 30, 22)             # plunger, face borders
FACE = (236, 226, 205)               # cream clock faces
FELT = (92, 136, 100)                # green felt lining of the captured-pieces tray
FELT_SHADOW = (58, 92, 66)
HOUR_INK = (40, 30, 22)
MINUTE_INK = (176, 58, 46)
CAPTION_BG = (20, 16, 12, 205)
CAPTION_EDGE = (232, 182, 92, 220)
LIGHT_SQ = (240, 217, 181)
DARK_SQ = (181, 136, 99)
LIGHT_HL = (214, 214, 120)
DARK_HL = (178, 168, 70)
CHECK_SQ = (235, 97, 80)
WHITE_PIECE = (255, 255, 255)
BLACK_PIECE = (24, 24, 24)
BLACK_DETAIL = (150, 150, 150)
PIECE_EDGE = (20, 20, 20)
TEXT = (245, 238, 228)
TEXT_DIM = (165, 150, 132)
BUTTON = (58, 50, 42)
BUTTON_SAVE = (88, 128, 70)
BUTTON_PRESSED = (232, 182, 92)      # a button lights up while it is held down
BUTTON_SAVE_PRESSED = (150, 205, 120)
BUTTON_PRESSED_TEXT = (30, 24, 18)

FONT_DIRS = [os.environ.get("FBCLOCK_FONTS", ""), "/usr/share/fonts/dejavu",
             "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"]

_font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for d in FONT_DIRS:
            path = os.path.join(d, name)
            if d and os.path.exists(path):
                _font_cache[key] = ImageFont.truetype(path, size)
                break
        else:
            raise SystemExit("fbclock: %s not found in %s" % (name, FONT_DIRS))
    return _font_cache[key]


REF_SIZE = 100


def fit_size(width_at_ref, max_width, start):
    """Text width scales with font size, so measure once at REF_SIZE and
    scale. (Loading a font per candidate size costs ~250KB each, which this
    32MB board can't spare.) Rounded down to even sizes so the font cache
    stays small."""
    size = int(REF_SIZE * max_width / max(width_at_ref, 1)) - 1
    return max(8, min(start, size)) & ~1


def fit_font(text, max_width, start, bold=False):
    """Largest font (<= start) at which text fits in max_width."""
    return font(fit_size(font(REF_SIZE, bold).getlength(text), max_width, start), bold)


# ------------------------------------------------------------------- chess

KNIGHT_STEPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_STEPS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
START_ROW = "RNBQKBNR"


def sq(name):
    """'e4' -> square index (0 = a1, 63 = h8)."""
    return (ord(name[0]) - 97) + (int(name[1]) - 1) * 8


class Position:
    """Just enough chess to replay games written in standard notation."""

    def __init__(self):
        self.board = [None] * 64
        for f in range(8):
            self.board[f] = START_ROW[f]
            self.board[8 + f] = "P"
            self.board[48 + f] = "p"
            self.board[56 + f] = START_ROW[f].lower()
        self.white = True
        self.ep = None  # en passant target square

    def own(self, p):
        return p is not None and p.isupper() == self.white

    def _reaches(self, frm, to, kind, white):
        """Can a piece of this kind on frm move to/attack to? (ignores pins)"""
        fx, fy, tx, ty = frm % 8, frm // 8, to % 8, to // 8
        dx, dy = tx - fx, ty - fy
        if kind == "N":
            return (dx, dy) in KNIGHT_STEPS
        if kind == "K":
            return max(abs(dx), abs(dy)) == 1
        dirs = {"R": ROOK_DIRS, "B": BISHOP_DIRS, "Q": ROOK_DIRS + BISHOP_DIRS}[kind]
        for sx, sy in dirs:
            x, y = fx + sx, fy + sy
            while 0 <= x < 8 and 0 <= y < 8:
                if x == tx and y == ty:
                    return True
                if self.board[y * 8 + x] is not None:
                    break
                x, y = x + sx, y + sy
        return False

    def attacked(self, target, by_white):
        for s, p in enumerate(self.board):
            if p is None or p.isupper() != by_white:
                continue
            kind = p.upper()
            if kind == "P":
                dy = 1 if by_white else -1
                if target // 8 - s // 8 == dy and abs(target % 8 - s % 8) == 1:
                    return True
            elif self._reaches(s, target, kind, by_white):
                return True
        return False

    def king_square(self, white):
        return self.board.index("K" if white else "k")

    def in_check(self):
        return self.attacked(self.king_square(self.white), not self.white)

    def _leaves_king_safe(self, frm, to):
        saved = self.board[:]
        self.board[to], self.board[frm] = self.board[frm], None
        if self.board[to].upper() == "P" and to == self.ep:
            self.board[to - 8 if self.white else to + 8] = None
        safe = not self.attacked(self.king_square(self.white), not self.white)
        self.board = saved
        return safe

    def play(self, san):
        """Play one SAN move; return the set of squares whose contents changed
        and the (from, to) squares."""
        move = san.rstrip("+#!?")
        changed = set()
        rank1 = 0 if self.white else 56
        if move in ("O-O", "0-0", "O-O-O", "0-0-0"):
            long = move.count("O") + move.count("0") == 3
            k_from, k_to = rank1 + 4, rank1 + (2 if long else 6)
            r_from, r_to = rank1 + (0 if long else 7), rank1 + (3 if long else 5)
            self.board[k_to], self.board[k_from] = self.board[k_from], None
            self.board[r_to], self.board[r_from] = self.board[r_from], None
            changed |= {k_from, k_to, r_from, r_to}
            self.ep = None
            self.white = not self.white
            return changed, (k_from, k_to)

        m = re.match(r"^([NBRQK])?([a-h])?([1-8])?x?([a-h][1-8])(?:=?([NBRQ]))?$", move)
        if not m:
            raise ValueError("can't read move %r" % san)
        kind, from_file, from_rank, target, promo = m.groups()
        kind = kind or "P"
        to = sq(target)
        capture = "x" in move

        candidates = []
        for s, p in enumerate(self.board):
            if not self.own(p) or p.upper() != kind:
                continue
            if from_file and s % 8 != ord(from_file) - 97:
                continue
            if from_rank and s // 8 != int(from_rank) - 1:
                continue
            if kind == "P":
                fwd = 8 if self.white else -8
                if capture:
                    ok = to - s in (fwd - 1, fwd + 1) and abs(to % 8 - s % 8) == 1
                else:
                    home = 1 if self.white else 6
                    ok = (to - s == fwd and self.board[to] is None) or (
                        to - s == 2 * fwd and s // 8 == home
                        and self.board[s + fwd] is None and self.board[to] is None)
            else:
                ok = self._reaches(s, to, kind, self.white) and not self.own(self.board[to])
            if ok:
                candidates.append(s)
        if len(candidates) > 1:
            candidates = [s for s in candidates if self._leaves_king_safe(s, to)]
        if len(candidates) != 1:
            raise ValueError("move %r matches %d pieces" % (san, len(candidates)))
        frm = candidates[0]

        piece = self.board[frm]
        if kind == "P" and to == self.ep and self.board[to] is None:
            victim = to - 8 if self.white else to + 8
            self.board[victim] = None
            changed.add(victim)
        if promo:
            piece = promo if self.white else promo.lower()
        self.board[to], self.board[frm] = piece, None
        changed |= {frm, to}
        self.ep = (frm + to) // 2 if kind == "P" and abs(to - frm) == 16 else None
        self.white = not self.white
        return changed, (frm, to)


def load_games(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    games = []
    for chunk in re.split(r"\n\s*\n(?=\[)", text.strip()):
        headers = dict(re.findall(r'^\[(\w+)\s+"(.*)"\]\s*$', chunk, re.M))
        body = re.sub(r"^\[.*\]\s*$", "", chunk, flags=re.M)
        body = re.sub(r"\{[^}]*\}|;[^\n]*", " ", body)          # comments
        while re.search(r"\([^()]*\)", body):                     # variations
            body = re.sub(r"\([^()]*\)", " ", body)
        body = re.sub(r"\$\d+|\d+\.(\.\.)?", " ", body)           # NAGs, move numbers
        moves = [t for t in body.split() if t not in ("1-0", "0-1", "1/2-1/2", "*")]
        if moves:
            games.append((headers, moves))
    return games


class GamePlayer:
    """Steps through the games, one move at a time."""

    def __init__(self, games):
        self.games = games
        self.order = []
        self.new_game()

    def new_game(self):
        if not self.order:
            last = getattr(self, "headers", None)
            self.order = list(range(len(self.games)))
            random.shuffle(self.order)
            if last is not None and len(self.order) > 1 and self.games[self.order[-1]][0] is last:
                self.order.insert(0, self.order.pop())
        self.headers, self.moves = self.games[self.order.pop()]
        self.pos = Position()
        self.ply = 0
        self.last_move = None
        self.check_sq = None

    @property
    def finished(self):
        return self.ply >= len(self.moves)

    def step(self):
        """Play the next move and return the squares that need redrawing."""
        dirty = set(self.last_move or ()) | ({self.check_sq} if self.check_sq is not None else set())
        san = self.moves[self.ply]
        try:
            changed, self.last_move = self.pos.play(san)
        except (ValueError, IndexError) as e:
            print("fbclock: skipping rest of %s: %s" % (self.headers.get("Event", "game"), e), flush=True)
            self.ply = len(self.moves)
            return dirty
        self.ply += 1
        self.check_sq = self.pos.king_square(self.pos.white) if san[-1] in "+#" else None
        dirty |= changed | set(self.last_move)
        if self.check_sq is not None:
            dirty.add(self.check_sq)
        return dirty

# ---------------------------------------------------------------- graphics

GLYPHS_OUTLINE = dict(zip("KQRBNP", "♔♕♖♗♘♙"))
GLYPHS_SOLID = dict(zip("KQRBNP", "♚♛♜♝♞♟"))


class BoardRenderer:
    """Draws single chess squares. The board is stretched to fill the screen,
    so squares are rectangles (cell_w x cell_h); pieces keep their shape."""

    def __init__(self, cell_w, cell_h):
        self.cell_w, self.cell_h = cell_w, cell_h
        size = min(cell_w, cell_h)
        self.piece_font = font(int(size * 0.90))
        self.coord_font = font(max(9, size // 6), bold=True)
        self.masks = {}                        # built the first time each piece is drawn
        self.sprites = {}

    def _glyph_mask(self, glyph, fnt):
        w, h = self.cell_w, self.cell_h
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((w / 2, h * 0.53), glyph, font=fnt, fill=255, anchor="mm")
        return mask

    @staticmethod
    def _silhouette(outline):
        """Fill the inside of an outline glyph: spread "outside" in from the
        edges one pixel at a time until it stops; whatever it never reaches
        is the piece. (Same result as a flood fill, but built from Pillow
        operations that run in C; Pillow's flood fill is pure Python and
        takes seconds per piece on this CPU.)"""
        ink = outline.point(lambda v: 255 if v > 60 else 0)
        space = ImageChops.invert(ink)
        w, h = ink.size
        reach = Image.new("L", ink.size, 0)
        ImageDraw.Draw(reach).rectangle((0, 0, w - 1, h - 1), outline=255)
        reach = ImageChops.darker(reach, space)
        for i in range(w + h):
            grown = reach
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                grown = ImageChops.lighter(grown, ImageChops.offset(reach, dx, dy))
            grown = ImageChops.darker(grown, space)
            if i % 6 == 5 and ImageChops.difference(grown, reach).getbbox() is None:
                break
            reach = grown
        return ImageChops.invert(reach)

    def tile(self, index, piece, highlight=False, check=False):
        w, h = self.cell_w, self.cell_h
        f, r = index % 8, index // 8
        light = (f + r) % 2 == 1
        if check:
            bg = CHECK_SQ
        elif highlight:
            bg = LIGHT_HL if light else DARK_HL
        else:
            bg = LIGHT_SQ if light else DARK_SQ
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        coord = DARK_SQ if light else LIGHT_SQ
        pad = max(2, min(w, h) // 20)
        if f == 0:
            d.text((pad, pad), str(r + 1), font=self.coord_font, fill=coord, anchor="lt")
        if r == 0:
            d.text((w - pad, h - pad), "abcdefgh"[f], font=self.coord_font, fill=coord, anchor="rs")
        if piece:
            rgb, mask = self.sprite(piece)
            img.paste(rgb, (0, 0), mask)
        return img

    def sprite(self, piece):
        """(colour image, mask) for a piece, cell-sized with the piece centred."""
        if piece not in self.sprites:
            kind = piece.upper()
            if kind not in self.masks:
                outline = self._glyph_mask(GLYPHS_OUTLINE[kind], self.piece_font)
                self.masks[kind] = (self._silhouette(outline), outline)
            solid, outline = self.masks[kind]
            if piece.isupper():
                rgb = Image.new("RGB", (self.cell_w, self.cell_h), WHITE_PIECE)
                rgb.paste(PIECE_EDGE, (0, 0), outline)
            else:
                rgb = Image.new("RGB", (self.cell_w, self.cell_h), BLACK_PIECE)
                rgb.paste(BLACK_DETAIL, (0, 0), outline.point(lambda v: v * 2 // 5))
            self.sprites[piece] = (rgb, ImageChops.lighter(solid, outline))
        return self.sprites[piece]


class Layout:
    """A true square board on the left, the chess-clock case beside it."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        cell = min(height, width * 3 // 5) // 8
        self.cell_w = self.cell_h = cell
        self.board_x, self.board_y = 0, (height - 8 * cell) // 2
        self.board_rect = (0, self.board_y, 8 * cell, self.board_y + 8 * cell)
        self.panel = (8 * cell, 0, width, height)

    def square_pos(self, index):
        f, r = index % 8, index // 8
        return self.board_x + f * self.cell_w, self.board_y + (7 - r) * self.cell_h


PIECE_ORDER = "QRBNP"


def captured_pieces(board):
    """Pieces each side has lost, most valuable first: (black's, white's).
    A promoted pawn shows up as an extra queen etc., so it isn't counted
    as a lost pawn."""
    start = {"Q": 1, "R": 2, "B": 2, "N": 2, "P": 8}
    out = []
    for white in (False, True):
        on = {k: sum(1 for p in board if p == (k if white else k.lower())) for k in start}
        promoted = sum(max(0, on[k] - start[k]) for k in "QRBN")
        lost = []
        for k in PIECE_ORDER:
            n = start[k] - on[k] - (promoted if k == "P" else 0)
            lost += [k if white else k.lower()] * max(0, n)
        out.append(lost)
    return tuple(out)


class ClockPanel:
    """The walnut chess-clock case: a plunger on top, an hour face and a
    minute face, and a tray of captured pieces. Every part can be drawn on
    its own so a change only rewrites what moved."""

    def __init__(self, layout):
        px0, py0, px1, py1 = layout.panel
        self.x0, self.y0 = px0, py0
        w, h = self.w, self.h = px1 - px0, py1 - py0
        m = max(12, w // 13)
        top, face_h, gap = int(h * 0.09), int(h * 0.335), int(h * 0.025)
        self.faces = {"hour": (m, top, w - m, top + face_h),
                      "minute": (m, top + face_h + gap, w - m, top + 2 * face_h + gap)}
        self.tray = (m, top + 2 * face_h + gap + int(h * 0.03), w - m, h - int(h * 0.03))
        self.border = max(4, w // 55)
        fw = w - 2 * m - 2 * self.border
        ref = font(REF_SIZE, True)
        cap_ratio = -ref.getbbox("0", anchor="ls")[1] / REF_SIZE
        size = min(fit_size(ref.getlength("88"), fw * 0.80, 300), int(face_h * 0.66 / cap_ratio))
        self.digit_font = font(size & ~1, True)
        self.cap = cap_ratio * (size & ~1)
        tray_h = self.tray[3] - self.tray[1]
        self.tray_piece = max(16, (tray_h - 6) // 2)
        self.tray_pieces = BoardRenderer(self.tray_piece, self.tray_piece)
        self.case = self._render_case()

    def _render_case(self):
        w, h = self.w, self.h
        img = Image.new("RGB", (w, h), CASE_WOOD)
        d = ImageDraw.Draw(img)
        for y in range(0, h, 6):                              # faint wood grain
            d.line((0, y, w, y + 3), fill=CASE_GRAIN)
        d.line((0, 0, 0, h), fill=CASE_DARK, width=3)         # edge against the board
        # the plunger sits just above the hour face; remember where, so it
        # can be redrawn pressed down
        top = self.faces["hour"][1]
        self.bar_h = max(8, h // 30)
        self.bar_y = max(4, top - self.bar_h - h // 40)
        self.press_depth = top - self.bar_y - self.bar_h - 2
        self.plunger_rect = (int(w * 0.36), self.bar_y, int(w * 0.64) + 1, top)
        # kept without the plunger (one copy saves ~half a megabyte); the
        # plunger is drawn on whenever the case is shown
        return img

    def _draw_plunger(self, d, offset, ox, oy):
        """Draw the plunger pushed down by offset pixels; (ox, oy) is where
        the image being drawn on sits within the case."""
        w, top = self.w, self.faces["hour"][1]
        cx, y = w / 2 - ox, self.bar_y + offset - oy
        d.rounded_rectangle((cx - w * 0.12, y, cx + w * 0.12, y + self.bar_h),
                            radius=self.bar_h // 2, fill=CASE_DARK)
        d.rectangle((cx - w * 0.03, y + self.bar_h - 2, cx + w * 0.03, top - oy), fill=CASE_DARK)

    def plunger(self, pressed):
        """(image, x, y) of the plunger area, with the plunger up or pushed in
        (pressed is how far, 0..1)."""
        img = self.case.crop(self.plunger_rect)
        self._draw_plunger(ImageDraw.Draw(img), int(self.press_depth * pressed),
                           *self.plunger_rect[:2])
        return img, self.x0 + self.plunger_rect[0], self.y0 + self.plunger_rect[1]

    def _box(self, rect):
        """The case behind rect, with an empty cream face drawn on it."""
        img = self.case.crop(rect)          # (faces and tray sit clear of the plunger)
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, img.width - 1, img.height - 1), radius=min(img.size) // 6,
            fill=FACE, outline=CASE_DARK, width=self.border)
        return img

    def face_base(self, key):
        return self._box(self.faces[key])

    def face(self, key, text):
        """(image, x, y) of a clock face showing text."""
        img = self.face_base(key)
        ImageDraw.Draw(img).text((img.width / 2, img.height / 2 + self.cap / 2), text,
                                 font=self.digit_font, anchor="ms",
                                 fill=HOUR_INK if key == "hour" else MINUTE_INK)
        x0, y0 = self.faces[key][:2]
        return img, self.x0 + x0, self.y0 + y0

    def _tray_box(self):
        """The tray: a felt-lined recess, squarer than the clock faces."""
        img = self.case.crop(self.tray)
        d = ImageDraw.Draw(img)
        r = max(3, min(img.size) // 14)
        d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=r, fill=FELT,
                            outline=CASE_DARK, width=max(2, self.border // 2))
        inset = max(2, self.border // 2)                      # shadow along the top and
        d.line((inset + r, inset, img.width - inset - r, inset), fill=FELT_SHADOW, width=3)
        d.line((inset, inset + r, inset, img.height - inset - r), fill=FELT_SHADOW, width=3)
        return img

    def tray_image(self, captured):
        """(image, x, y) of the tray: black's lost pieces above white's."""
        img = self._tray_box()
        size, pad = self.tray_piece, self.border + 2
        for row, pieces in enumerate(captured):
            if not pieces:
                continue
            step = min(size * 0.8, (img.width - 2 * pad - size) / max(1, len(pieces) - 1))
            x = (img.width - (step * (len(pieces) - 1) + size)) / 2
            y = (img.height - 2 * size) // 2 + row * size
            for p in pieces:
                rgb, mask = self.tray_pieces.sprite(p)
                img.paste(rgb, (int(x), y), mask)
                x += step
        return img, self.x0 + self.tray[0], self.y0 + self.tray[1]

    def full(self, hour, minute, captured):
        img = self.case.copy()
        self._draw_plunger(ImageDraw.Draw(img), 0, 0, 0)
        for part in (self.face("hour", hour), self.face("minute", minute), self.tray_image(captured)):
            img.paste(part[0], (part[1] - self.x0, part[2] - self.y0))
        return img, self.x0, self.y0


def render_caption(layout, headers):
    """A rounded label naming the game, e.g. "The Opera Game, 1858" over
    "Paul Morphy vs Duke Karl / Count Isouard". Returns [(RGBA image, x, y)]
    placed near the bottom of the screen."""
    title = headers.get("Event", "").strip()
    year = headers.get("Date", "")[:4].strip("?.")
    if year:
        title = "%s, %s" % (title, year) if title else year
    players = "%s vs %s" % (headers.get("White", "?"), headers.get("Black", "?"))
    if not title:
        return []
    bx0, by0, bx1, by1 = layout.board_rect
    w, h = bx1 - bx0, layout.height
    max_w = int(w * 0.90)
    tfont = fit_font(title, max_w, max(14, h // 18), bold=True)
    pfont = fit_font(players, max_w, max(12, h // 24))
    pad_x, pad_y, gap = h // 30, h // 50, h // 90
    text_w = int(max(tfont.getlength(title), pfont.getlength(players)))
    cw, ch = text_w + 2 * pad_x, tfont.size + gap + pfont.size + 2 * pad_y + 4
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=ch // 4, fill=CAPTION_BG,
                        outline=CAPTION_EDGE, width=2)
    d.text((cw / 2, pad_y), title, font=tfont, fill=ACCENT, anchor="mt")
    d.text((cw / 2, pad_y + tfont.size + gap), players, font=pfont, fill=TEXT, anchor="mt")
    # sit just above the bottom edge of the board
    return [(img, bx0 + (w - cw) // 2, by1 - ch - h // 40)]


def bounds(layers):
    """Bounding rectangle of a list of (image, x, y) layers."""
    if not layers:
        return None
    return (min(x for _, x, _ in layers), min(y for _, _, y in layers),
            max(x + i.width for i, x, _ in layers), max(y + i.height for i, _, y in layers))


# ------------------------------------------------------------- time setter

class TimeSetter:
    """The settings screen: up/down spinners for the hour, minute and AM/PM,
    daytime and night-time brightness sliders, and Cancel, Rotate (turn the
    display upside down) and Save. The date is left as it is.

    Buttons are keyed ("up", column), ("down", column), "cancel", "rotate" and
    "save"; the sliders are "day" and "night". Each part can be drawn on its
    own, so a press only redraws the little that changed."""

    FIELDS = ("hour", "minute", "ampm")
    LABELS = ("Hour", "Minute", "")
    SLIDER_LABELS = {"day": "Daytime brightness", "night": "Night-time brightness"}
    REPEAT_DELAY = 0.5        # hold an arrow this long and it starts repeating...
    REPEAT_EVERY = 0.12       # ...this often

    def __init__(self, layout, now, day=DEFAULT_DAY, night=DEFAULT_NIGHT):
        self.layout = layout
        self.values = {"hour": now.tm_hour % 12 or 12, "minute": now.tm_min,
                       "ampm": now.tm_hour >= 12, "day": day, "night": night}
        self.start_time = (self.values["hour"], self.values["minute"], self.values["ampm"])
        w, h = layout.width, layout.height
        # the time on the left...
        self.col_w = int(w * 0.14)
        gap = int(w * 0.018)
        left = int(w * 0.03)
        self.cols = [left + i * (self.col_w + gap) for i in range(3)]
        self.top = int(h * 0.20)
        self.btn_h = int(h * 0.15)
        self.val_h = int(h * 0.20)
        # ...the brightness sliders on the right
        sx0, sx1 = self.cols[2] + self.col_w + int(w * 0.07), w - int(w * 0.04)
        track_h = int(h * 0.085)
        self.sliders = {}
        for i, key in enumerate(("day", "night")):
            label_y = self.top + i * int(h * 0.25)
            ty0 = label_y + int(h * 0.075)
            self.sliders[key] = {"area": (sx0 - track_h // 2, label_y, sx1 + track_h // 2, ty0 + track_h + 4),
                                 "track": (sx0, ty0, sx1, ty0 + track_h)}
        bottom_y = int(h * 0.80)
        bw = int(w * 0.26)
        bgap = (w - 3 * bw) // 4
        self.boxes = {}
        for i, cx in enumerate(self.cols):
            val_top = self.top + self.btn_h
            self.boxes[("up", i)] = (cx, self.top, cx + self.col_w, val_top)
            self.boxes[("down", i)] = (cx, val_top + self.val_h, cx + self.col_w,
                                       val_top + self.val_h + self.btn_h)
        for i, key in enumerate(("cancel", "rotate", "save")):
            x0 = bgap + i * (bw + bgap)
            self.boxes[key] = (x0, bottom_y, x0 + bw, h - int(h * 0.04))
        self.label_font = font(int(h * 0.04))
        self.value_font = font(int(h * 0.11), True)
        self.arrow_font = font(int(h * 0.08))
        self.button_font = font(int(h * 0.06), True)
        self.last_tap = time.monotonic()

    # -- behaviour

    def hit(self, x, y, slack=8):
        """The button or slider under (x, y), allowing a little slack."""
        for key, sl in self.sliders.items():
            x0, y0, x1, y1 = sl["track"]
            if x0 - 20 <= x <= x1 + 20 and y0 - 20 <= y <= y1 + 20:
                return key
        for key, (x0, y0, x1, y1) in self.boxes.items():
            if x0 - slack <= x <= x1 + slack and y0 - slack <= y <= y1 + slack:
                return key
        return None

    def spin(self, key):
        """Apply an arrow press; returns the column whose value changed."""
        direction, i = key
        delta = 1 if direction == "up" else -1
        v, field = self.values, self.FIELDS[i]
        if field == "hour":
            v["hour"] = (v["hour"] - 1 + delta) % 12 + 1
        elif field == "minute":
            v["minute"] = (v["minute"] + delta) % 60
        elif field == "ampm":
            v["ampm"] = not v["ampm"]
        return i

    def repeats(self, key):
        return isinstance(key, tuple) and self.FIELDS[key[1]] != "ampm"

    def slide(self, key, x):
        """Move a brightness slider to x; returns True if its value changed."""
        x0, _, x1, _ = self.sliders[key]["track"]
        value = round((x - x0) / (x1 - x0) * 100)
        value = min(100, max(MIN_BRIGHTNESS, value))
        changed = value != self.values[key]
        self.values[key] = value
        return changed

    def time_changed(self):
        v = self.values
        return (v["hour"], v["minute"], v["ampm"]) != self.start_time

    def apply(self):
        """Set the clock to the chosen time, keeping today's date. Nothing is
        changed if the time wasn't touched (so the seconds aren't reset)."""
        if not self.time_changed():
            return
        v, today = self.values, time.localtime()
        hour = v["hour"] % 12 + (12 if v["ampm"] else 0)
        stamp = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, hour, v["minute"], 0, 0, 0, -1))
        time.clock_settime(time.CLOCK_REALTIME, stamp)

    def expired(self):
        return time.monotonic() - self.last_tap > SETTER_TIMEOUT

    # -- drawing

    def render_button(self, key, pressed=False):
        """(image, x, y) for one button, drawn up or pressed."""
        x0, y0, x1, y1 = self.boxes[key]
        img = Image.new("RGB", (x1 - x0, y1 - y0), BG)
        d = ImageDraw.Draw(img)
        save = key == "save"
        if pressed:
            fill, colour = (BUTTON_SAVE_PRESSED if save else BUTTON_PRESSED), BUTTON_PRESSED_TEXT
        else:
            fill, colour = (BUTTON_SAVE if save else BUTTON), TEXT
        d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=12, fill=fill)
        if isinstance(key, tuple):
            label, fnt = ("▲" if key[0] == "up" else "▼"), self.arrow_font
        else:
            label, fnt = key.capitalize(), self.button_font
        d.text((img.width / 2, img.height / 2), label, font=fnt, fill=colour, anchor="mm")
        return img, x0, y0

    def value_text(self, i):
        v = self.values
        return ("%d" % v["hour"], "%02d" % v["minute"], "PM" if v["ampm"] else "AM")[i]

    def render_value(self, i):
        """(image, x, y) for one column's current value."""
        cx, top = self.cols[i], self.top + self.btn_h
        img = Image.new("RGB", (self.col_w, self.val_h), BG)
        text = self.value_text(i)
        fnt = fit_font(text, self.col_w, self.value_font.size, True)
        ImageDraw.Draw(img).text((self.col_w / 2, self.val_h / 2), text, font=fnt, fill=TEXT,
                                 anchor="mm")
        return img, cx, top

    def render_slider(self, key):
        """(image, x, y) for a brightness slider with its label and value."""
        ax0, ay0, ax1, ay1 = self.sliders[key]["area"]
        tx0, ty0, tx1, ty1 = self.sliders[key]["track"]
        img = Image.new("RGB", (ax1 - ax0, ay1 - ay0), BG)
        d = ImageDraw.Draw(img)
        value = self.values[key]
        d.text((tx0 - ax0, 0), self.SLIDER_LABELS[key], font=self.label_font, fill=TEXT_DIM, anchor="lt")
        d.text((tx1 - ax0, 0), "%d%%" % value, font=self.label_font, fill=ACCENT, anchor="rt")
        r = (ty1 - ty0) // 2
        knob_x = tx0 + (tx1 - tx0) * value / 100 - ax0
        y0, y1 = ty0 - ay0 + r * 0.55, ty1 - ay0 - r * 0.55          # slim groove
        d.rounded_rectangle((tx0 - ax0, y0, tx1 - ax0, y1), radius=int(r * 0.45), fill=BUTTON)
        d.rounded_rectangle((tx0 - ax0, y0, knob_x, y1), radius=int(r * 0.45), fill=ACCENT)
        cy = (ty0 + ty1) / 2 - ay0
        d.ellipse((knob_x - r, cy - r, knob_x + r, cy + r), fill=TEXT, outline=BUTTON, width=2)
        return img, ax0, ay0

    def render(self, x0, x1):
        """Render the horizontal slice [x0, x1) of the whole settings screen."""
        w, h = self.layout.width, self.layout.height
        img = Image.new("RGB", (x1 - x0, h), BG)
        d = ImageDraw.Draw(img)
        d.text((w / 2 - x0, h * 0.09), "Settings", font=font(int(h * 0.065), True),
               fill=ACCENT, anchor="mm")
        for key, sl in self.sliders.items():
            if x0 <= sl["area"][2] and sl["area"][0] <= x1:
                part, px, py = self.render_slider(key)
                img.paste(part, (px - x0, py))
        for i, cx in enumerate(self.cols):
            if x0 <= cx + self.col_w and cx <= x1:
                d.text((cx + self.col_w / 2 - x0, self.top - h * 0.025), self.LABELS[i],
                       font=self.label_font, fill=TEXT_DIM, anchor="ms")
                part, px, py = self.render_value(i)
                img.paste(part, (px - x0, py))
        colon_x = (self.cols[0] + self.col_w + self.cols[1]) / 2 - x0
        d.text((colon_x, self.top + self.btn_h + self.val_h / 2), ":", font=self.value_font,
               fill=TEXT, anchor="mm")
        for key, box in self.boxes.items():
            if x0 <= box[2] and box[0] <= x1:
                part, px, py = self.render_button(key)
                img.paste(part, (px - x0, py))
        return img


# ---------------------------------------------------------------- hardware

def pack_pixels(img, bpp):
    """An RGB image as screen bytes for a framebuffer of this depth."""
    if bpp == 32:
        return img.tobytes("raw", "BGRX")
    if bpp == 24:
        return img.tobytes("raw", "BGR")
    # RGB565 little-endian, built with lookup tables so it stays in C code
    r, g, b = img.split()
    hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
    return Image.merge("LA", (lo, hi)).tobytes()


class Framebuffer:
    def __init__(self, device):
        sysfs = "/sys/class/graphics/" + os.path.basename(device)

        def read(attr):
            with open(os.path.join(sysfs, attr)) as f:
                return f.read().strip()

        self.width, self.height = (int(v) for v in read("virtual_size").split(","))
        try:
            mode = read("modes").splitlines()[0]  # e.g. "U:800x480p-60"
            w, h = mode.split(":", 1)[1].split("p")[0].split("x")
            self.width, self.height = int(w), int(h)
        except (OSError, IndexError, ValueError):
            pass
        self.bpp = int(read("bits_per_pixel"))
        if self.bpp not in (16, 24, 32):
            raise SystemExit("fbclock: unsupported framebuffer depth: %d bpp" % self.bpp)
        self.bytes_pp = self.bpp // 8
        try:
            self.stride = int(read("stride"))
        except OSError:
            self.stride = self.width * self.bytes_pp
        self.fd = os.open(device, os.O_RDWR)
        # map the screen's memory into the program, so drawing is a plain
        # memory copy instead of two system calls per row; fall back to
        # writing the device if mapping isn't possible
        try:
            self.mem = mmap.mmap(self.fd, self.stride * self.height, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE)
        except (OSError, ValueError):
            self.mem = None

    def _pack(self, img):
        return pack_pixels(img, self.bpp)

    rotated = False                   # draw everything upside down

    def _orient(self, img, x, y):
        """Turned upside down, an image lands in the opposite corner, rotated."""
        if not self.rotated:
            return img, x, y
        return (img.transpose(Image.Transpose.ROTATE_180),
                self.width - x - img.width, self.height - y - img.height)

    def prepare(self, img, x, y):
        """Convert an image to screen bytes now, to write later with show()."""
        img, x, y = self._orient(img, x, y)
        return (self._pack(img), img.width, img.height, x, y)

    def show(self, prepared):
        data, w, h, x, y = prepared
        self._write(data, w, h, x, y)

    def blit(self, img, x, y):
        img, x, y = self._orient(img, x, y)
        self._write(self._pack(img), img.width, img.height, x, y)

    def _write(self, data, width, height, x, y):
        row = width * self.bytes_pp
        offset = y * self.stride + x * self.bytes_pp
        if self.mem is not None:
            mem, stride, src = self.mem, self.stride, memoryview(data)
            if row == stride:
                mem[offset:offset + len(data)] = src
            else:
                for i in range(height):
                    o = offset + i * stride
                    mem[o:o + row] = src[i * row:(i + 1) * row]
            return
        if row == self.stride:
            os.lseek(self.fd, offset, os.SEEK_SET)
            os.write(self.fd, data)
            return
        for i in range(height):
            os.lseek(self.fd, offset + i * self.stride, os.SEEK_SET)
            os.write(self.fd, data[i * row:(i + 1) * row])

    def fill(self, color):
        strip = 32
        for y in range(0, self.height, strip):
            self.blit(Image.new("RGB", (self.width, min(strip, self.height - y)), color), 0, y)


class Touch:
    """Taps from the board's on-board NS2009 resistive touch chip (U4 on the
    schematic), polled over I2C. The touch film on the 40-pin LCD connector is
    wired to this chip, not to the F1C100s's own touch controller."""

    I2C_SLAVE = 0x0703                 # ioctl: set the address for read/write
    ADDRESS = 0x48
    CMD_X, CMD_Y, CMD_Z1, CMD_Z2 = 0xC0, 0xD0, 0xE0, 0xF0
    PRESS_Z1 = 150                     # pressure: idle reads <60, a press 300+
    POLL_SECS = 0.05                   # how often to check while idle...
    FAST_POLL_SECS = 0.02              # ...and while a press or the setter is active
    MIN_SAMPLES = 3                    # a press counts after 3 steady readings
    MAX_SPREAD = 300                   # (raw units, ~60px): noise jumps around
    RELEASE_SECS = 0.12                # no pressure for this long = released

    def __init__(self, bus, width, height):
        self.fd = os.open(bus, os.O_RDWR)
        fcntl.ioctl(self.fd, self.I2C_SLAVE, self.ADDRESS)
        self._measure(self.CMD_Z1)     # raises OSError if the chip doesn't answer
        self.width, self.height = width, height
        self.samples = []
        self.down = False
        self.quiet = 0
        self.last_pressed = 0.0
        self.pos = (0, 0, 0, 0)
        cfg = {"TOUCH_X_MIN": 0, "TOUCH_X_MAX": 4095, "TOUCH_Y_MIN": 0, "TOUCH_Y_MAX": 4095,
               "TOUCH_SWAP_XY": 0}
        try:
            with open(CONFIG_FILE) as f:
                for line in f:
                    k, _, v = line.partition("=")
                    if k.strip() in cfg:
                        cfg[k.strip()] = int(v.strip())
        except (OSError, ValueError):
            pass
        self.cfg = cfg

    @classmethod
    def open(cls, width, height):
        bus = os.environ.get("FBCLOCK_TOUCH_BUS", "/dev/i2c-0")
        try:
            return cls(bus, width, height)
        except OSError as e:
            print("fbclock: no touch chip on %s: %s" % (bus, e), flush=True)
            return None

    def _measure(self, cmd):
        os.write(self.fd, bytes([cmd]))
        hi, lo = os.read(self.fd, 2)
        return (hi << 4) | (lo >> 4)   # 12-bit result

    rotated = False                   # the display is upside down

    def to_screen(self, rx, ry):
        c = self.cfg
        if c["TOUCH_SWAP_XY"]:
            rx, ry = ry, rx
        x = (rx - c["TOUCH_X_MIN"]) * self.width / ((c["TOUCH_X_MAX"] - c["TOUCH_X_MIN"]) or 1)
        y = (ry - c["TOUCH_Y_MIN"]) * self.height / ((c["TOUCH_Y_MAX"] - c["TOUCH_Y_MIN"]) or 1)
        x, y = min(self.width - 1, max(0, int(x))), min(self.height - 1, max(0, int(y)))
        if self.rotated:
            x, y = self.width - 1 - x, self.height - 1 - y
        return x, y

    def poll(self):
        """Take one reading. Returns [("down", x, y, raw_x, raw_y)] as soon as a
        press is confirmed (a few steady readings), [("move", ...)] when a
        held finger slides, [("up", ...)] when it ends, and [] otherwise."""
        try:
            # same order as the sequence verified on the board (X, Y, Z1, Z2);
            # reading pressure on its own straight after idle did not
            # register presses
            x, y = self._measure(self.CMD_X), self._measure(self.CMD_Y)
            pressed = self._measure(self.CMD_Z1) >= self.PRESS_Z1
            self._measure(self.CMD_Z2)
        except OSError:
            return []
        now = time.monotonic()
        if pressed:
            self.quiet, self.last_pressed = 0, now
            self.samples = (self.samples + [(x, y)])[-8:]
            if not self.down and len(self.samples) >= self.MIN_SAMPLES:
                recent = self.samples[-self.MIN_SAMPLES:]
                xs, ys = sorted(p[0] for p in recent), sorted(p[1] for p in recent)
                if max(xs[-1] - xs[0], ys[-1] - ys[0]) <= self.MAX_SPREAD:
                    self.down = True
                    rx, ry = xs[len(xs) // 2], ys[len(ys) // 2]
                    self.pos = self.to_screen(rx, ry) + (rx, ry)
                    print("fbclock: press raw=(%d,%d) at %s" % (rx, ry, self.pos[:2]), flush=True)
                    return [("down",) + self.pos]
            elif self.down and len(self.samples) >= self.MIN_SAMPLES:
                recent = self.samples[-self.MIN_SAMPLES:]
                rx = sorted(p[0] for p in recent)[len(recent) // 2]
                ry = sorted(p[1] for p in recent)[len(recent) // 2]
                sx, sy = self.to_screen(rx, ry)
                if abs(sx - self.pos[0]) + abs(sy - self.pos[1]) >= 4:   # ignore jitter
                    self.pos = (sx, sy, rx, ry)
                    return [("move",) + self.pos]
            return []
        if not self.samples:
            return []
        # pressure dips briefly mid-press; only call it released after a
        # short quiet spell
        self.quiet += 1
        if self.quiet < 2 or now - self.last_pressed < self.RELEASE_SECS:
            return []
        if not self.down:
            xs, ys = [p[0] for p in self.samples], [p[1] for p in self.samples]
            print("fbclock: ignored touch: %d readings, spread %d" % (
                len(xs), max(max(xs) - min(xs), max(ys) - min(ys))), flush=True)
        was_down, self.down, self.samples, self.quiet = self.down, False, [], 0
        return [("up",) + self.pos] if was_down else []


class Backlight:
    """Screen brightness through Linux's backlight interface (the panel's
    backlight is dimmed by PWM; see the board's device tree)."""

    def __init__(self, path):
        self.path = path
        with open(os.path.join(path, "max_brightness")) as f:
            self.max = int(f.read())

    @classmethod
    def find(cls):
        base = "/sys/class/backlight"
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return None
        for n in names:
            try:
                return cls(os.path.join(base, n))
            except (OSError, ValueError):
                pass
        return None

    def set(self, percent):
        # eyes judge brightness roughly logarithmically, so square the
        # fraction: the slider then has fine steps at the dim end
        level = max(1, round(self.max * (percent / 100) ** 2))
        try:
            with open(os.path.join(self.path, "brightness"), "w") as f:
                f.write(str(level))
        except OSError as e:
            print("fbclock: could not set brightness: %s" % e, flush=True)


def render_splash(width, height):
    """The boot splash: a white knight on the walnut of the clock case.
    (The knight is drawn straight from the font: filling it the way the
    board's pieces are filled is slow at this size.)"""
    img = Image.new("RGB", (width, height), CASE_WOOD)
    d = ImageDraw.Draw(img)
    for y in range(0, height, 6):                             # faint wood grain
        d.line((0, y, width, y + 3), fill=CASE_GRAIN)
    knight = font(int(height * 0.5))
    centre = (width / 2, height * 0.37)
    d.text(centre, GLYPHS_SOLID["N"], font=knight, fill=WHITE_PIECE, anchor="mm")
    d.text(centre, GLYPHS_OUTLINE["N"], font=knight, fill=PIECE_EDGE, anchor="mm")
    d.text((width / 2, height * 0.76), "Chess Clock", font=font(int(height * 0.12), True),
           fill=ACCENT, anchor="mm")
    return img


def splash_name(width, height, bpp, rotated):
    """Splash files are named for the screen they suit; the boot script
    (S00splash) only uses one whose name matches the screen it finds."""
    return "splash-%dx%dx%d-%d.raw.gz" % (width, height, bpp, 1 if rotated else 0)


def write_splash(path, width, height, bpp, rotated):
    """Save the splash as compressed screen bytes, converted a strip at a
    time so it never needs much memory."""
    img = render_splash(width, height)
    if rotated:
        img = img.transpose(Image.Transpose.ROTATE_180)
    tmp = path + ".tmp"
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
            for y in range(0, height, 48):
                gz.write(pack_pixels(img.crop((0, y, width, min(height, y + 48))), bpp))
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(tmp, path)


def read_setting(key, default=None):
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    except OSError:
        pass
    return default


def save_setting(key, value):
    save_settings({key: value})


def save_settings(values):
    """Set KEY=value lines in the config file, keeping everything else in it.
    Written to a new file, flushed to the SD card, then swapped in, so losing
    power part-way can't leave a half-written config."""
    try:
        with open(CONFIG_FILE) as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for key, value in values.items():
        line = "%s=%s" % (key, value)
        for i, old in enumerate(lines):
            if old.partition("=")[0].strip() == key:
                lines[i] = line
                break
        else:
            lines.append(line)
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
        fd = os.open(os.path.dirname(CONFIG_FILE) or ".", os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        print("fbclock: could not save settings: %s" % e, flush=True)


def quiet_console():
    """Stop the text console from drawing over the clock."""
    try:
        with open("/sys/class/graphics/fbcon/cursor_blink", "w") as f:
            f.write("0")
    except OSError:
        pass
    for tty in ("/dev/tty1", "/dev/tty0"):
        try:
            with open(tty, "w") as f:
                # hide cursor, disable screen blanking and powerdown (no clearing:
                # the boot splash stays up until the clock is drawn over it)
                f.write("\033[?25l\033[9;0]\033[14;0]")
            break
        except OSError:
            pass


# -------------------------------------------------------------------- main

class App:
    def __init__(self, fb, touch):
        self.fb, self.touch = fb, touch
        self.layout = Layout(fb.width, fb.height)
        self.board = BoardRenderer(self.layout.cell_w, self.layout.cell_h)
        self.player = GamePlayer(load_games(GAMES_FILE))
        self.panel = ClockPanel(self.layout)
        self.ready_flip = None                 # ((old, new), frames) built ahead of time
        self.pending = []                      # touches noticed during animations
        face = self.panel.faces["hour"]
        self.promo_pieces = BoardRenderer(*(int((face[3] - face[1]) * 0.62),) * 2)
        for piece in "PQ":
            self.promo_pieces.sprite(piece)
        self.shown_captured = None
        self.caption_layers = []               # the game's name, briefly
        self.caption_until = 0.0
        self.shown_time = None                 # (hour, minute) on screen
        self.setter = None
        self.held = None
        self.repeat_at = 0.0
        self.backlight = Backlight.find()
        self.shown_brightness = None
        self.load_brightness_settings()

    def poll_touch(self):
        """Check the touch chip and queue anything that happened. Called
        every frame of every animation as well as by the main loop, so a tap
        during a piece slide or a minute flip isn't missed."""
        if self.touch:
            self.pending.extend(self.touch.poll())

    @staticmethod
    def hour_minute(lt):
        return "%d" % (lt.tm_hour % 12 or 12), "%02d" % lt.tm_min

    def draw_panel(self):
        lt = time.localtime()
        self.shown_time = (lt.tm_hour, lt.tm_min)
        self.shown_captured = captured_pieces(self.player.pos.board)
        self.fb.blit(*self.panel.full(*self.hour_minute(lt), self.shown_captured))

    def update_tray(self):
        captured = captured_pieces(self.player.pos.board)
        if captured != self.shown_captured:
            self.shown_captured = captured
            self.fb.blit(*self.panel.tray_image(captured))

    def load_brightness_settings(self):
        def number(key, default):
            try:
                return min(100, max(MIN_BRIGHTNESS, int(read_setting(key, default))))
            except ValueError:
                return default

        def minutes(key, default):
            try:
                h, m = read_setting(key, default).split(":")
                return int(h) * 60 + int(m)
            except ValueError:
                h, m = default.split(":")
                return int(h) * 60 + int(m)
        self.day = number("DAY_BRIGHTNESS", DEFAULT_DAY)
        self.night = number("NIGHT_BRIGHTNESS", DEFAULT_NIGHT)
        self.night_start = minutes("NIGHT_START", DEFAULT_NIGHT_START)
        self.night_end = minutes("NIGHT_END", DEFAULT_NIGHT_END)

    def is_night(self, lt=None):
        lt = lt or time.localtime()
        now = lt.tm_hour * 60 + lt.tm_min
        if self.night_start <= self.night_end:
            return self.night_start <= now < self.night_end
        return now >= self.night_start or now < self.night_end    # spans midnight

    def apply_brightness(self, percent=None):
        """Set the backlight: an explicit percent (a slider being dragged),
        or by default the daytime/night-time setting for right now."""
        if percent is None:
            percent = self.night if self.is_night() else self.day
        if self.backlight and percent != self.shown_brightness:
            self.backlight.set(percent)
            self.shown_brightness = percent

    def tick(self):
        """Keep the clock faces current; on the hour, a pawn promotes."""
        lt = time.localtime()
        if (lt.tm_hour, lt.tm_min) == self.shown_time:
            return
        self.apply_brightness()                # day/night may have changed
        old_hour = self.shown_time and self.hour_minute(
            time.struct_time((0, 0, 0, self.shown_time[0]) + (0,) * 5))[0]
        old_minute = self.shown_time and "%02d" % self.shown_time[1]
        self.shown_time = (lt.tm_hour, lt.tm_min)
        hour, minute = self.hour_minute(lt)
        if old_minute:
            ready, self.ready_flip = self.ready_flip, None
            if ready and ready[0] == (old_minute, minute):
                self.play_frames(ready[1])          # built in advance: right on time
            else:
                self.flip_minute(old_minute, minute)
        else:
            self.fb.blit(*self.panel.face("minute", minute))
        if old_hour and old_hour != hour:
            self.promote(old_hour, hour)
        else:
            self.fb.blit(*self.panel.face("hour", hour))

    def prepare_next_flip(self):
        """Shortly before the minute turns over, build its flip in advance so
        it plays exactly on the minute instead of a second late."""
        lt = time.localtime()
        if lt.tm_sec < 58 or (lt.tm_hour, lt.tm_min) != self.shown_time:
            return
        old, new = "%02d" % lt.tm_min, "%02d" % ((lt.tm_min + 1) % 60)
        if not (self.ready_flip and self.ready_flip[0] == (old, new)):
            self.ready_flip = ((old, new), self.flip_frames(old, new))

    def flip_minute(self, old, new):
        self.play_frames(self.flip_frames(old, new))

    def flip_frames(self, old, new):
        """Frames for a minute change, which plays like a chess clock being
        pressed: the plunger dips, and the minute face flips over like a
        split-flap display - the top half of the old number folds down to
        reveal the new one.

        Every frame is built before any is shown, then they are played back
        on an even beat; building frames while playing made it stutter."""
        panel = self.panel
        old_img, fx, fy = panel.face("minute", old)
        new_img = panel.face("minute", new)[0]
        w, h = old_img.size
        mid = h // 2
        seam = max(2, panel.border // 2)

        def flip_frame(k):
            frame = old_img.copy()                  # behind the flap: new number
            frame.paste(new_img.crop((0, 0, w, mid)), (0, 0))  # on top, old below
            if k < 0.5:                             # old top half folds down towards us
                flap, fh = old_img.crop((0, 0, w, mid)), max(1, int(mid * (1 - 2 * k)))
                shade, y = 0.5 * k, mid - fh
            else:                                   # then the new bottom half drops in
                flap, fh = new_img.crop((0, mid, w, h)), max(1, int((h - mid) * (2 * k - 1)))
                shade, y = 0.5 * (1 - k), mid
            flap = Image.blend(flap.resize((w, fh)), Image.new("RGB", (w, fh), CASE_DARK), shade)
            frame.paste(flap, (0, y))
            ImageDraw.Draw(frame).rectangle((0, mid - seam // 2, w, mid + seam // 2), fill=CASE_DARK)
            return frame

        def timeline():
            steps = 3
            for i in range(1, steps + 1):
                yield PRESS_SECS * i / steps, panel.plunger(i / steps)
            for i in range(1, FLIP_FRAMES):
                yield PRESS_SECS + FLIP_SECS * i / FLIP_FRAMES, (flip_frame(i / FLIP_FRAMES), fx, fy)
            yield PRESS_SECS + FLIP_SECS, (new_img, fx, fy)
            for i in range(1, steps + 1):
                yield PRESS_SECS + FLIP_SECS + PRESS_SECS * i / steps, panel.plunger(1 - i / steps)

        return self.prepare_frames(timeline(), on_screen=[(old_img, fx, fy), panel.plunger(0.0)])

    def prepare_frames(self, timeline, on_screen=()):
        """Show (seconds from start, (image, x, y)) frames on time.

        Everything is prepared before playback starts, and each frame keeps
        only the rectangle that differs from the previous frame at that spot
        (on_screen says what is showing there to begin with), so playback is
        just copying a few small strips of ready-made screen bytes."""
        prepare = getattr(self.fb, "prepare", None)
        last = {(x, y, img.size): img for img, x, y in on_screen}
        frames = []
        for t, (img, x, y) in timeline:
            self.poll_touch()
            key = (x, y, img.size)
            before, last[key] = last.get(key), img
            if before is not None:
                box = ImageChops.difference(img, before).getbbox()
                if box is None:
                    continue                    # nothing changed
                img, x, y = img.crop(box), x + box[0], y + box[1]
            frames.append((t, prepare(img, x, y) if prepare else (img, x, y)))
        return frames

    def play_frames(self, frames):
        prepare = getattr(self.fb, "prepare", None)
        t0 = time.monotonic()
        for t, frame in frames:
            self.poll_touch()
            wait = t0 + t - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if prepare:
                self.fb.show(frame)
            else:
                self.fb.blit(*frame)

    def promote(self, old, new):
        """The hour changes: the old hour fades, a pawn marches up the face,
        promotes to a queen with a flash, and the queen becomes the new hour."""
        panel = self.panel
        base = panel.face_base("hour")
        old_img, fx, fy = panel.face("hour", old)
        new_img = panel.face("hour", new)[0]
        pieces = self.promo_pieces
        size = pieces.cell_w
        cx, cy = (base.width - size) // 2, (base.height - size) // 2
        fade, march, crown, reveal = PROMOTE_SECS
        t0 = time.monotonic()
        while True:
            t = time.monotonic() - t0
            if t < fade:
                frame = Image.blend(old_img, base, t / fade)
            elif t < fade + march:
                k = (t - fade) / march
                e = k * k * (3 - 2 * k)
                y = base.height + (cy - base.height) * e - abs(math.sin(k * math.pi * 3)) * size * 0.12
                frame = base.copy()
                rgb, mask = pieces.sprite("P")
                frame.paste(rgb, (cx, int(y)), mask)
            elif t < fade + march + crown:
                k = (t - fade - march) / crown
                frame = base.copy()
                d = ImageDraw.Draw(frame)
                r = size * (0.45 + 0.35 * k)                 # a gold ring bursts out
                d.ellipse((base.width / 2 - r, base.height / 2 - r, base.width / 2 + r,
                           base.height / 2 + r), outline=ACCENT, width=max(2, int(6 * (1 - k)) + 1))
                rgb, mask = pieces.sprite("Q")
                frame.paste(rgb, (cx, cy), mask)
            elif t < fade + march + crown + reveal:
                k = (t - fade - march - crown) / reveal
                queen = base.copy()
                rgb, mask = pieces.sprite("Q")
                queen.paste(rgb, (cx, cy), mask)
                frame = Image.blend(queen, new_img, k)
            else:
                break
            self.fb.blit(frame, fx, fy)
            self.poll_touch()
        self.fb.blit(new_img, fx, fy)

    def draw_squares(self, squares):
        L = self.layout
        for s in squares:
            sx, sy = L.square_pos(s)
            self.draw_region((sx, sy, sx + L.cell_w, sy + L.cell_h))

    def render_region(self, rect, tile_for, sprites=()):
        """Render any rectangle of the screen: board squares from tile_for(s),
        then sliding pieces [(piece, x, y)], then the game caption on top."""
        L = self.layout
        x0, y0 = max(0, rect[0]), max(0, rect[1])
        x1, y1 = min(L.width, rect[2]), min(L.height, rect[3])
        img = Image.new("RGB", (x1 - x0, y1 - y0), BG)
        for s in range(64):
            sx, sy = L.square_pos(s)
            if sx < x1 and sx + L.cell_w > x0 and sy < y1 and sy + L.cell_h > y0:
                img.paste(tile_for(s), (sx - x0, sy - y0))
        for piece, px, py in sprites:
            rgb, mask = self.board.sprite(piece)
            img.paste(rgb, (px - x0, py - y0), mask)
        for layer, lx, ly in self.caption_layers:
            if lx < x1 and lx + layer.width > x0 and ly < y1 and ly + layer.height > y0:
                # pasting with the image as its own mask blends it by its alpha
                img.paste(layer, (lx - x0, ly - y0), layer)
        return img, x0, y0

    def play_move(self):
        """Play the next move, sliding the piece (and the rook, when castling)
        across the board rather than making it jump."""
        p, L = self.player, self.layout
        before = p.pos.board[:]
        old_marks = set(p.last_move or ()) | ({p.check_sq} if p.check_sq is not None else set())
        dirty = p.step()
        if not p.last_move or before == p.pos.board:
            self.draw_squares(dirty)
            return
        frm, to = p.last_move
        movers = [(before[frm], frm, to)]
        if before[frm] in "Kk" and abs(to - frm) == 2:          # castling: the rook comes too
            rook_from, rook_to = (frm + 3, frm + 1) if to > frm else (frm - 4, frm - 1)
            movers.append((before[rook_from], rook_from, rook_to))

        # while pieces slide: the old position minus the moving pieces (so a
        # captured piece stays visible until it is landed on), with the new
        # move's squares highlighted
        board = before[:]
        for _, f, _ in movers:
            board[f] = None
        tiles = {}

        def tile_for(s):
            if s not in tiles:
                tiles[s] = self.board.tile(s, board[s], s in (frm, to))
            return tiles[s]

        for s in old_marks | {frm, to} | {f for _, f, _ in movers}:
            sx, sy = L.square_pos(s)
            self.fb.blit(*self.render_region((sx, sy, sx + L.cell_w, sy + L.cell_h), tile_for))

        starts = [L.square_pos(f) for _, f, _ in movers]
        ends = [L.square_pos(t) for _, _, t in movers]
        shown = list(starts)
        t0 = time.monotonic()
        while True:
            t = min(1.0, (time.monotonic() - t0) / SLIDE_SECS)
            e = t * t * (3 - 2 * t)                           # ease in and out
            now = [(round(a[0] + (b[0] - a[0]) * e), round(a[1] + (b[1] - a[1]) * e))
                   for a, b in zip(starts, ends)]
            sprites = [(m[0], x, y) for m, (x, y) in zip(movers, now)]
            for (ax, ay), (bx, by) in zip(shown, now):
                # repaint where the piece was and where it is now, in one go
                rect = (min(ax, bx), min(ay, by), max(ax, bx) + L.cell_w, max(ay, by) + L.cell_h)
                self.fb.blit(*self.render_region(rect, tile_for, sprites))
            shown = now
            self.poll_touch()
            if t >= 1.0:
                break
        # settle into the real position: captures removed, check shown
        self.draw_squares(dirty | old_marks | {frm, to})
        self.update_tray()

    def draw_region(self, rect):
        """Redraw a rectangle of the current position in one write, so it
        appears at once instead of filling in square by square."""
        p = self.player
        hl = set(p.last_move or ())
        self.fb.blit(*self.render_region(
            rect, lambda s: self.board.tile(s, p.pos.board[s], s in hl, s == p.check_sq)))

    def draw_board(self):
        """The whole board, written in a few horizontal bands: each band
        appears at once, and only one band is held in memory at a time."""
        bx0, by0, bx1, by1 = self.layout.board_rect
        band = 2 * self.layout.cell_h
        for y in range(by0, by1, band):
            self.draw_region((bx0, y, bx1, min(by1, y + band)))
            self.poll_touch()

    def show_caption(self, draw=True):
        self.caption_layers = render_caption(self.layout, self.player.headers)
        self.caption_until = time.monotonic() + CAPTION_SECS
        if draw and self.caption_layers:
            self.draw_region(bounds(self.caption_layers))

    def hide_caption(self):
        area = bounds(self.caption_layers)
        self.caption_layers = []
        if area:
            self.draw_region(area)

    def draw_all(self):
        L = self.layout
        if L.board_rect[1] > 0:
            self.fb.fill(BG)                   # board doesn't reach the screen edges
        self.draw_board()
        self.draw_panel()

    def draw_setter(self):
        half = self.layout.width // 2
        for x0, x1 in ((0, half), (half, self.layout.width)):
            self.fb.blit(self.setter.render(x0, x1), x0, 0)

    def paint_button(self, key, pressed):
        self.fb.blit(*self.setter.render_button(key, pressed))

    def paint_value(self, i):
        self.fb.blit(*self.setter.render_value(i))

    def paint_slider(self, key):
        self.fb.blit(*self.setter.render_slider(key))

    def handle_touch(self, kind, x, y):
        """React to a press starting ("down"), sliding ("move") or ending ("up")."""
        now = time.monotonic()
        if self.setter is None:
            if kind == "down":                 # any press on the clock opens settings
                self.setter = TimeSetter(self.layout, time.localtime(), self.day, self.night)
                self.held = None
                self.draw_setter()
            return
        st = self.setter
        st.last_tap = now
        if kind == "move":
            if self.held in st.sliders and st.slide(self.held, x):
                self.paint_slider(self.held)
                self.apply_brightness(st.values[self.held])   # preview while dragging
            return
        if kind == "down":
            key = st.hit(x, y)
            self.held = key
            if key is None:
                return
            if key in st.sliders:
                st.slide(key, x)
                self.paint_slider(key)
                self.apply_brightness(st.values[key])
                return
            self.paint_button(key, True)       # show it pressed straight away
            if isinstance(key, tuple):         # arrows act on press, and repeat if held
                self.paint_value(st.spin(key))
                self.repeat_at = now + st.REPEAT_DELAY
            return
        key, self.held = self.held, None
        if key is None or key in st.sliders:
            return
        self.paint_button(key, False)
        if key == "rotate":                    # flip the display and remember it
            self.set_rotation(not self.fb.rotated)
            self.draw_setter()
            return
        if key in ("cancel", "save"):          # these act on release, so a slip is harmless
            if key == "save":
                try:
                    st.apply()
                except (OSError, OverflowError, ValueError) as e:
                    print("fbclock: could not set time: %s" % e, flush=True)
                self.day, self.night = st.values["day"], st.values["night"]
                save_settings({"DAY_BRIGHTNESS": self.day, "NIGHT_BRIGHTNESS": self.night})
            self.close_setter()

    def close_setter(self):
        self.setter = None
        self.held = None
        self.apply_brightness()                # back to the saved day/night level
        self.draw_all()

    def ensure_splash(self):
        """Make sure a boot splash exists for this screen and orientation.
        The image ships with matching files already; this only fills a gap
        (a different screen, say)."""
        fb = self.fb
        if not hasattr(fb, "stride") or fb.stride != fb.width * fb.bpp // 8:
            return                     # the boot script copies whole rows; needs a plain layout
        path = os.path.join(SPLASH_DIR, splash_name(fb.width, fb.height, fb.bpp, fb.rotated))
        if os.path.exists(path):
            return
        try:
            write_splash(path, fb.width, fb.height, fb.bpp, fb.rotated)
        except OSError as e:
            print("fbclock: could not save the boot splash: %s" % e, flush=True)

    def set_rotation(self, rotated):
        self.fb.rotated = rotated
        if self.touch:
            self.touch.rotated = rotated
        self.ready_flip = None                 # frames built for the old way up
        save_setting("ROTATE", 1 if rotated else 0)
        self.ensure_splash()

    def repeat_held(self):
        """Keep stepping an arrow while it is held down."""
        st, key = self.setter, self.held
        if st and st.repeats(key) and time.monotonic() >= self.repeat_at:
            self.paint_value(st.spin(key))
            self.repeat_at = time.monotonic() + st.REPEAT_EVERY
            st.last_tap = time.monotonic()

    def run(self):
        self.apply_brightness()
        self.show_caption(draw=False)
        self.draw_all()
        self.ensure_splash()
        next_move = time.monotonic() + START_HOLD_SECS
        while True:
            now = time.monotonic()
            timeout = max(0.05, min(next_move - now, 1.0))
            if self.touch:
                busy = self.setter is not None or self.touch.samples
                time.sleep(Touch.FAST_POLL_SECS if busy else Touch.POLL_SECS)
                self.poll_touch()
                while self.pending:
                    kind, x, y, _, _ = self.pending.pop(0)
                    self.handle_touch(kind, x, y)
            else:
                time.sleep(timeout)

            if self.setter is not None:
                self.repeat_held()
                if self.setter.expired():
                    self.close_setter()
                continue

            now = time.monotonic()
            if now >= next_move:
                p = self.player
                if p.finished:
                    p.new_game()
                    self.show_caption(draw=False)
                    self.draw_board()
                    self.update_tray()
                    next_move = now + START_HOLD_SECS
                else:
                    self.play_move()
                    next_move = time.monotonic() + (END_HOLD_SECS if p.finished else MOVE_SECS - SLIDE_SECS)
            if self.caption_layers and time.monotonic() >= self.caption_until:
                self.hide_caption()
            self.prepare_next_flip()
            self.tick()


def preview(path):
    w, h = (int(v) for v in os.environ.get("FBCLOCK_SIZE", "800x480").split("x"))
    layout = Layout(w, h)
    out = Image.new("RGB", (w, h), BG)
    if os.environ.get("FBCLOCK_PREVIEW_SETTER"):
        setter = TimeSetter(layout, time.localtime())
        out.paste(setter.render(0, w // 2), (0, 0))
        out.paste(setter.render(w // 2, w), (w // 2, 0))
    else:
        class ImageScreen:
            width, height, bpp = w, h, 32

            def blit(self, img, x, y):
                out.paste(img, (x, y))

            def fill(self, color):
                out.paste(color, (0, 0, w, h))
        app = App(ImageScreen(), None)
        player = app.player
        while not player.finished and player.ply < int(os.environ.get("FBCLOCK_PLY", "999")):
            player.step()
        if player.ply < 6:
            app.show_caption(draw=False)
        app.draw_all()
    out.save(path)


def touch_debug():
    fb = Framebuffer(os.environ.get("FBCLOCK_DEVICE", "/dev/fb0"))
    t = Touch.open(fb.width, fb.height)
    if not t:
        raise SystemExit("touch chip not responding")
    print("tap the screen corners; Ctrl-C to stop", flush=True)
    while True:
        time.sleep(Touch.FAST_POLL_SECS)
        for kind, x, y, rx, ry in t.poll():
            print("%-4s raw x=%4d y=%4d  ->  screen x=%3d y=%3d" % (kind, rx, ry, x, y), flush=True)


def main():
    if "--touch-debug" in sys.argv:
        return touch_debug()
    if len(sys.argv) == 4 and sys.argv[1] == "--make-splash":
        # e.g. fbclock.py --make-splash OUTDIR 800x480x32 (both orientations)
        w, h, bpp = (int(v) for v in sys.argv[3].split("x"))
        for rotated in (False, True):
            write_splash(os.path.join(sys.argv[2], splash_name(w, h, bpp, rotated)), w, h, bpp, rotated)
        return
    if os.environ.get("FBCLOCK_PREVIEW"):
        return preview(os.environ["FBCLOCK_PREVIEW"])

    fb = Framebuffer(os.environ.get("FBCLOCK_DEVICE", "/dev/fb0"))
    touch = Touch.open(fb.width, fb.height)
    fb.rotated = read_setting("ROTATE", "0") == "1"
    if touch:
        touch.rotated = fb.rotated
    print("fbclock: %dx%d %dbpp, touch: %s" % (fb.width, fb.height, fb.bpp, "yes" if touch else "no"),
          flush=True)
    quiet_console()
    App(fb, touch).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
