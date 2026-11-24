#!/usr/bin/env python3
"""Check that every game in a PGN file replays with the clock's own move
reader, so a typo in a newly added game is caught before it reaches the
board (where the clock would skip the rest of that game).

usage: apps/chess/tools/check_games.py [PGN_FILE]     (default: apps/chess/games.pgn)"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "apps", "chess"))
os.environ.setdefault("FBCLOCK_PREVIEW", "1")
import fbclock as F                                # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "apps", "chess", "games.pgn")
bad = 0
for headers, moves in F.load_games(path):
    pos, name = F.Position(), headers.get("Event", "?")
    try:
        for i, san in enumerate(moves):
            pos.play(san)
        print("ok    %-40s %3d moves" % (name, (len(moves) + 1) // 2))
    except (ValueError, IndexError) as e:
        bad += 1
        print("FAIL  %-40s move %d (%s): %s" % (name, i // 2 + 1, san, e))
sys.exit(1 if bad else 0)
