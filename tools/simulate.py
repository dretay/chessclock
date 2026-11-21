#!/usr/bin/env python3
"""Exercise the clock on a desktop, against an in-memory screen: plays a
game with captures and a checkmate, and one with a pawn promoting with a
capture, saving every few frames as PNGs; then checks the touch behaviour
(a quick tap shows the caption, a short hold does nothing, a long hold opens
Settings). Needs Pillow and the DejaVu fonts.

usage: simulate.py FONT_DIR [OUT_DIR]     (default OUT_DIR: ./sim-out)
e.g.   tools/simulate.py /opt/homebrew/share/fonts/dejavu
Exits non-zero if a check fails."""
import os
import sys
import time

if len(sys.argv) < 2:
    sys.exit(__doc__)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[2] if len(sys.argv) > 2 else "sim-out"
os.environ.update(FBCLOCK_FONTS=sys.argv[1], FBCLOCK_GAMES=os.path.join(REPO, "clock", "games.pgn"),
                  FBCLOCK_PREVIEW="1")             # (keeps the clock from caching drawings)
sys.path.insert(0, os.path.join(REPO, "clock"))
import fbclock as F                                # noqa: E402
from PIL import Image                              # noqa: E402

os.makedirs(OUT, exist_ok=True)
screen = Image.new("RGB", (800, 480))
saving, frame = None, [0]


class Screen:
    width, height, bpp, rotated = 800, 480, 32, False

    def blit(self, img, x, y):
        screen.paste(img, (x, y))
        frame[0] += 1
        if saving and frame[0] % 4 == 0:
            screen.save(os.path.join(OUT, "%s-%03d.png" % (saving, frame[0])))

    def fill(self, colour):
        screen.paste(colour, (0, 0, 800, 480))


app = F.App(Screen(), None)
failures = []


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        failures.append(what)


def play(name, headers, moves):
    """Play a game, saving frames of its last two moves (and any checkmate)."""
    global saving
    p = app.player
    p.headers, p.moves = headers, moves
    p.pos, p.ply, p.last_move, p.check_sq, p.mated = F.Position(), 0, None, None, False
    app.fallen, app.caption_layers = None, []
    app.draw_all()
    while not p.finished:
        saving = name if p.ply >= len(moves) - 2 else None
        app.play_move()
    if p.mated:
        saving = name + "-mate"
        app.topple_king()
    saving = None
    screen.save(os.path.join(OUT, name + "-end.png"))
    return p


p = play("legal", {"White": "Legal", "Black": "Saint Brie"},
         "e4 e5 Bc4 d6 Nf3 Bg4 Nc3 g6 Nxe5 Bxd1 Bxf7+ Ke7 Nd5#".split())
check(p.mated and app.fallen == p.pos.king_square(False), "checkmate topples the black king")
check(len(F.captured_pieces(p.pos.board)[0]) == 2, "tray holds black's two lost pieces")
p = play("promotion", {"Event": "Promotion test", "White": "A", "Black": "B"}, "e4 d5 exd5 c6 dxc6 Nf6 cxb7 Nbd7 bxa8=Q".split())
check(p.pos.board[F.sq("a8")] == "Q", "pawn promotes to a queen on a8")


def press(secs):
    app.handle_touch("down", 300, 200)
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs and app.setter is None:
        app.update_hold()
        time.sleep(0.02)
    app.handle_touch("up", 300, 200)


app.caption_layers = []
press(0.2)
check(bool(app.caption_layers) and app.setter is None, "a quick tap shows the game's caption")
press(1.0)
check(app.setter is None and app.hold_shown == 0, "a 1-second hold doesn't open Settings")
press(F.HOLD_SECS + 0.3)
check(app.setter is not None, "a %.0f-second hold opens Settings" % F.HOLD_SECS)
screen.save(os.path.join(OUT, "settings.png"))
print("\nframes saved in %s/" % OUT)
sys.exit(1 if failures else 0)
