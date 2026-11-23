#!/usr/bin/env python3
"""Switch the board's serial console to a faster speed until it reboots (it starts at 115200).

usage: fast_serial.py [BAUD]          (default 1562500)
then:  export CLOCK_BAUD=1562500      so push_to_board.py and run_on_board.py use it

The board's UART runs from a 100 MHz clock, so it can only make 6.25 MHz / n: asking it for
1500000 gives 1562500, which the CP2102 adapter can match: about 150 KB/s, 13x the usual 115200.
921600, 1000000, 2000000 and 3000000 come out too far from anything the adapter makes. 460800
works too. The app must be stopped while copying at these speeds (push_to_board.py does that),
or the board drops bytes.

If the new speed doesn't answer, the board recovers by itself: a background job ends the shell
after a few seconds unless told the speed works, and the login prompt that comes back is at
115200. (Changing the speed back with stty from a background job doesn't work: busybox's shell
restores its own saved settings, speed included, at the next line typed.) `fast_serial.py 115200`
goes back by hand.
"""
import sys
import time

import serial

import boardlib

BOARD_RATE = {1562500: 1500000}            # what to ask the board for, to get this speed

if boardlib.USB:
    sys.exit("using the board's USB serial port (%s), which has no speed to set" % boardlib.PORT)
mac = int(sys.argv[1]) if len(sys.argv) > 1 else 1562500
ask = BOARD_RATE.get(mac, mac)


def answers(baud, secs=1.5):
    p = serial.Serial(boardlib.PORT, baud, timeout=0.05)
    p.reset_input_buffer()
    p.write(b"\n")
    out = boardlib.read_until(p, b"# ", secs)
    p.close()
    return b"# " in out or b"login:" in out or b"Password:" in out


now = next((b for b in dict.fromkeys((boardlib.BAUD, 115200, 460800, 1562500)) if answers(b)), None)
if now is None:
    sys.exit("the board isn't answering at any of the usual speeds")
if now == mac:
    print("console already at %d: export CLOCK_BAUD=%d" % (mac, mac))
    sys.exit(0)
port = serial.Serial(boardlib.PORT, now, timeout=0.05)
boardlib.login(port)
# the UART interrupts on its first byte rather than half full (the driver takes it for a 16550A,
# whose "half" is 8 of 16 bytes, but this chip's FIFO is 64: half is 32, too little room at
# these speeds, and it overruns)
port.write(b"echo 1 > /sys/class/tty/ttyS0/rx_trig_bytes\n")
time.sleep(0.3)
port.write(("rm -f /tmp/fast_ok; P=$$; ( trap '' TTOU TTIN HUP; sleep 5; [ -f /tmp/fast_ok ] || kill -9 $P ) "
            "</dev/null >/dev/null 2>&1 & sleep 0.3; stty %d\n" % ask).encode())
time.sleep(0.6)
port.close()
port = serial.Serial(boardlib.PORT, mac, timeout=0.05)
port.write(b"\ntouch /tmp/fast_ok; echo FAST-$((40+2))\n")
if b"FAST-42\r\n" not in boardlib.read_until(port, b"FAST-42\r\n", 2):
    sys.exit("no answer at %d; the board comes back at 115200 in a few seconds" % mac)
print("console at %d: export CLOCK_BAUD=%d" % (mac, mac))
