"""Shared helpers for talking to the board over its serial console.

The port defaults to the CP2102 adapter's name on macOS; set CLOCK_SERIAL to
use another (e.g. /dev/ttyUSB0 on Linux)."""
import os
import time

import serial

PORT = os.environ.get("CLOCK_SERIAL", "/dev/cu.usbserial-0001")
BAUD = 115200


def open_port(timeout=0.05):
    return serial.Serial(PORT, BAUD, timeout=timeout)


def read_until(port, marker, secs):
    """Read until marker (bytes) turns up or secs pass; returns what was read."""
    out = b""
    end = time.time() + secs
    while time.time() < end and marker not in out:
        out += port.read(65536)
    return out


def login(port):
    """Get to a root shell prompt, logging in (root/root) if needed."""
    port.write(b"\n")
    out = read_until(port, b"# ", 3)
    if b"# " in out:
        return
    if b"login:" not in out:
        port.write(b"\n")
        out = read_until(port, b"login:", 5)
    port.write(b"root\n")
    read_until(port, b"Password:", 5)
    port.write(b"root\n")
    if b"# " not in read_until(port, b"# ", 10):
        raise SystemExit("could not log in on %s" % PORT)
