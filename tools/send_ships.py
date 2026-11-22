#!/usr/bin/env python3
"""Send Disney ship positions to the board's fleet map over the serial console (until the ESP32
fetches them from AIS itself). The map rereads the file whenever it next shows.

usage:
  send_ships.py FILE                                    the whole file (format: vacation/ships_example.csv)
  send_ships.py --ship NAME LAT LON [HEADING [SPEED]]   one ship, stamped with the time now
  send_ships.py --clear                                 remove it (the map goes back to the example positions)

e.g.  tools/send_ships.py vacation/ships_example.csv
      tools/send_ships.py --ship Dream 27.3 -79.1 125 18

Writes /var/lib/vacation/ships.csv. One line per ship; a later line for the same ship replaces an
earlier one, so --ship just adds a line.
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "/var/lib/vacation/ships.csv"


def board(*commands):
    subprocess.run([sys.executable, os.path.join(HERE, "run_on_board.py"), "--wait", "3", *commands], check=True)


args = sys.argv[1:]
if not args:
    sys.exit(__doc__)
if args[0] == "--clear":
    board("rm -f %s; echo removed" % REMOTE)
elif args[0] == "--ship":
    if len(args) < 4: sys.exit(__doc__)
    name = args[1] if args[1].startswith("Disney ") else "Disney " + args[1]
    lat, lon = float(args[2]), float(args[3])
    heading = float(args[4]) if len(args) > 4 else 0
    speed = float(args[5]) if len(args) > 5 else 0
    # local time as text: the board's clock is set to local time (it has no time zone of its own)
    line = "%s,%.4f,%.4f,%.0f,%.1f,%s" % (name, lat, lon, heading, speed, time.strftime("%Y-%m-%dT%H:%M:%S"))
    board("mkdir -p %s; echo '%s' >> %s; tail -3 %s" % (os.path.dirname(REMOTE), line, REMOTE, REMOTE))
else:
    path = args[0]
    lines = [l for l in open(path).read().splitlines() if l.strip()]
    subprocess.run([sys.executable, os.path.join(HERE, "push_to_board.py"), path, REMOTE], check=True)
    print("sent %d lines" % len(lines))
