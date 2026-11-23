"""Shared helpers for talking to the board over its serial console.

The board's own USB serial port (its micro-USB port plugged into the Mac: Linux's USB serial
gadget, 0525:a4a7) is used when it's there: about 7x faster than UART0 at its fastest. Otherwise the CP2102 adapter on UART0. CLOCK_SERIAL picks a port by name instead (e.g.
/dev/ttyUSB0 on Linux)."""
import os
import time

import serial

UART = "/dev/cu.usbserial-0001"
GADGET = (0x0525, 0xA4A7)                 # Linux's USB serial gadget (g_serial, CDC ACM)


def board_usb_port():
    """The board's USB serial port, if it's plugged in (the /dev/cu. name, on macOS)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = sorted((p.device for p in list_ports.comports() if (p.vid, p.pid) == GADGET),
                   key=lambda d: "/cu." not in d)
    return ports[0] if ports else None


USB_PORT = board_usb_port()
PORT = os.environ.get("CLOCK_SERIAL") or USB_PORT or UART
USB = PORT == USB_PORT
BAUD = int(os.environ.get("CLOCK_BAUD", "115200"))   # UART0's own is 115200 (see fast_serial.py); USB ignores it


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
