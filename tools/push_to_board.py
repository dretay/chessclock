#!/usr/bin/env python3
"""Copy a file to the board over the serial console, near line speed
(about 10KB/s: a minute for the clock program, five for a kernel).

usage: push_to_board.py LOCAL_FILE REMOTE_PATH
e.g.   tools/push_to_board.py clock/fbclock.py /usr/lib/python3.11/site-packages/fbclock.py

Runs `cat > /root/xfer.b64` on the board (only after it confirms with a
marker, so the data can never reach the shell as commands), streams the file
as base64 throttled to just under the 115200-baud line rate (the console has
no flow control), ends with Ctrl-D, then decodes it into place and compares
checksums. Needs a little free space in /root for the base64 copy."""
import base64
import hashlib
import sys
import time

import boardlib

if len(sys.argv) != 3:
    sys.exit(__doc__)
src, dst = sys.argv[1], sys.argv[2]
raw = open(src, "rb").read()
want = hashlib.md5(raw).hexdigest()
b64 = base64.b64encode(raw).decode()
lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
port = boardlib.open_port()
boardlib.login(port)

# the marker is computed by the shell, so the echoed command itself can't match
port.write(b"rm -f /root/xfer.b64; stty -echo; echo XFER-$((40+2)); cat > /root/xfer.b64\n")
if b"XFER-42\r\n" not in boardlib.read_until(port, b"XFER-42\r\n", 10):
    sys.exit("board did not start receiving; nothing sent")
time.sleep(0.3)
rate = 10000.0                                  # bytes per second, < 11520 line rate
t0, sent = time.time(), 0
for i, line in enumerate(lines):
    data = (line + "\n").encode()
    port.write(data)
    sent += len(data)
    ahead = sent / rate - (time.time() - t0)
    if ahead > 0:
        time.sleep(ahead)
    if i % 2000 == 0:
        port.read(65536)
        sys.stderr.write("\r%3d%%" % (100 * i // len(lines)))
        sys.stderr.flush()
time.sleep(0.5)
port.write(b"\x04")                             # Ctrl-D: end of input for cat
boardlib.read_until(port, b"# ", 30)
port.write(b"stty echo; echo DONE-$((40+2))\n")
boardlib.read_until(port, b"DONE-42\r\n", 15)
port.write(("base64 -d /root/xfer.b64 > %s && rm /root/xfer.b64 && md5sum %s\n" % (dst, dst)).encode())
out = boardlib.read_until(port, want.encode(), 60)
ok = want.encode() in out
print("\n%s %s (%d bytes in %.0fs)" % ("copied" if ok else "FAILED: checksum mismatch for", dst,
                                       len(raw), time.time() - t0))
sys.exit(0 if ok else 1)
