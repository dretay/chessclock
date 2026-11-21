#!/usr/bin/env python3
"""Run shell commands on the board over the serial console and print what
comes back (logging in first if needed).

usage: run_on_board.py [--wait SECONDS] COMMAND [COMMAND ...]
  --wait  how long to collect output after the last command (default 3)

e.g.  tools/run_on_board.py "tail /var/lib/fbclock/fbclock.log"
      tools/run_on_board.py --wait 20 "/etc/init.d/S99fbclock restart"
"""
import sys
import time

import boardlib

args = sys.argv[1:]
wait = 3.0
if args[:1] == ["--wait"]:
    wait, args = float(args[1]), args[2:]
if not args:
    sys.exit(__doc__)
port = boardlib.open_port(timeout=0.2)
boardlib.login(port)
for command in args:
    port.write(command.encode() + b"\n")
    time.sleep(0.3)
out = b""
end = time.time() + wait
while time.time() < end:
    out += port.read(4096)
sys.stdout.write(out.decode(errors="replace"))
