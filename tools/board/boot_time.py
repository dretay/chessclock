#!/usr/bin/env python3
"""Time a boot from power-on: prints the serial console output with seconds
since power-on in front of each line, then a summary of the main stages.

usage: boot_time.py [--bench URL DEVICE CHANNEL] [--secs N]
  --bench  switch the power off and on through a lab-bench server's control
           API (POSTs {"control": "chN_output", "value": false/true} to
           URL/api/devices/DEVICE/controls); without it, you are asked to
           power-cycle the board yourself
  --secs   how long to record (default 30)

e.g.  tools/board/boot_time.py --bench http://localhost:8000 dp832a 1

U-Boot's lines come out as they happen. The kernel's own timestamps start
when it has unpacked itself, and with `quiet` it prints little, so the
summary relies on the lines that do appear."""
import json
import sys
import time
import urllib.request

import boardlib

args, secs, bench = sys.argv[1:], 30.0, None
while args:
    if args[0] == "--bench":
        bench, args = args[1:4], args[4:]
    elif args[0] == "--secs":
        secs, args = float(args[1]), args[2:]
    else:
        sys.exit(__doc__)


def power(on):
    url, device, channel = bench
    req = urllib.request.Request(
        "%s/api/devices/%s/controls" % (url.rstrip("/"), device),
        data=json.dumps({"control": "ch%s_output" % channel, "value": on}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=30).read()


port = boardlib.open_port()
if bench:
    power(False)
    time.sleep(2)
else:
    input("Switch the board off, then press Enter and switch it on straight away... ")
end = time.time() + 0.5                         # drop anything left over in the buffers
while time.time() < end:
    port.read(65536)
if bench:
    power(True)
t0 = time.time()
lines, line = [], b""
while time.time() - t0 < secs:
    for byte in port.read(4096):
        if byte == 10:
            lines.append((time.time() - t0, line.decode(errors="replace").rstrip()))
            line = b""
        else:
            line += bytes([byte])
for t, text in lines:
    print("%6.2f  %s" % (t, text))

stages = [("U-Boot starts", "U-Boot 20"), ("kernel starts", "Starting kernel"),
          ("init starts", "Run /sbin/init"), ("system scripts", "Starting syslogd"),
          ("clock started", "Starting fbclock"), ("login prompt", "login:")]
print("\nsummary (seconds from power-on):")
for name, marker in stages:
    t = next((t for t, text in lines if marker in text), None)
    print("  %-16s %s" % (name, "%.2f" % t if t is not None else "(not seen)"))
