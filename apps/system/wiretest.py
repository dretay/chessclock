"""The Nano's side of the ESP32 wiring test (tools/wifi/wiretest/: flashed on the ESP32 in place of its WiFi
firmware). Each of the ESP's six signal pins plays its own rhythm (high, then low, for 5, 7, 11, 13, 17 or
19 ms); this listens on the Nano's six pins and names the ESP pin each one hears (right, swapped, silent,
garbled), then pulls the ESP's reset line (EN) low a moment: every rhythm stopping for the restart says the
reset wire is right too.

To listen, the pins are taken from the WiFi: its driver stopped (S35wifi stop: PE2, PE9, PE10 freed) and
the SPI controller unbound (PA0-PA3 freed); afterwards the controller is bound again (its pins back to SPI)
and the WiFi started. The pins are read through Linux's GPIO character device (/dev/gpiochip0, the v2
ioctls: no library needed).

On a desktop: analyse() alone (samples in, findings out), for testing.
"""
import ctypes, fcntl, os, subprocess, time

# (Nano header label, pin, its line on gpiochip0: bank * 32 + pin, what it's for, the ESP pin it should hear)
WIRES = [("A0", "PA0", 0, "SPI CS", "TDO (IO15)"), ("A1", "PA1", 1, "SPI MOSI", "TCK (IO13)"),
         ("A2", "PA2", 2, "SPI clock", "TMS (IO14)"), ("A3", "PA3", 3, "SPI MISO", "TDI (IO12)"),
         ("D6", "PE9", 4 * 32 + 9, "handshake", "IO2"), ("D7", "PE10", 4 * 32 + 10, "data ready", "IO4")]
RESET = ("PCLK", "PE2", 4 * 32 + 2)                      # -> ESP EN
# the ESP pins' rhythms (half a period, ms): wiretest/main/main.c's table
RHYTHM = {"TDO (IO15)": 5, "TCK (IO13)": 7, "TMS (IO14)": 11, "TDI (IO12)": 13, "IO2": 17, "IO4": 19}
SPI_DEV, SPI_DRIVER = "1c06000.spi", "/sys/bus/platform/drivers/sun6i-spi"

# ---------------------------------------------------------------- what the samples say
def analyse(times, levels):
    """times: when each sample was taken (s); levels: per line, its samples (0 or 1). -> per line
    (verdict, the ESP pin heard or None, half-period measured ms): verdict "right", "swapped", "silent"
    (no rhythm: stuck high or low), "garbled" (changing, but no one rhythm: touching another wire?)."""
    out = []
    for (label, pin, _, role, want), lv in zip(WIRES, levels):
        edges = [times[i] for i in range(1, len(lv)) if lv[i] != lv[i - 1]]
        if len(edges) < 6: out.append(("silent", None, None)); continue
        gaps = sorted((b - a) * 1000 for a, b in zip(edges, edges[1:]))
        half = gaps[len(gaps) // 2]                                    # (the median: a missed sample doesn't matter)
        heard = min(RHYTHM, key=lambda k: abs(RHYTHM[k] - half))
        steady = sum(1 for g in gaps if abs(g - RHYTHM[heard]) <= 2.5) / len(gaps)
        if abs(RHYTHM[heard] - half) > 1.6 or steady < 0.7: out.append(("garbled", None, round(half, 1))); continue
        out.append(("right" if heard == want else "swapped", heard, round(half, 1)))
    return out


def report(found, reset):
    """(headline, [lines]) for the WiFi page: each Nano pin and what it heard, then the reset wire."""
    lines, bad = [], 0
    hearers = {}
    for (label, pin, _, role, want), (verdict, heard, half) in zip(WIRES, found):
        if heard: hearers.setdefault(heard, []).append(label)
    for (label, pin, _, role, want), (verdict, heard, half) in zip(WIRES, found):
        if verdict == "right": lines.append("%s %s: from %s. Right." % (label, role, want)); continue
        bad += 1
        if verdict == "swapped":
            other = next((l for (l, _, _, _, w) in WIRES if w == heard), "?")
            lines.append("%s %s: hears %s, should be %s (that's %s's)." % (label, role, heard, want, other))
        elif verdict == "silent": lines.append("%s %s: hears nothing. Check the wire from %s." % (label, role, want))
        else: lines.append("%s %s: garbled. Touching another wire? (from %s)" % (label, role, want))
    if reset is None: lines.append("Reset (PCLK to EN): not tested.")
    elif reset: lines.append("Reset (PCLK to EN): the ESP restarted. Right.")
    else: bad += 1; lines.append("Reset (PCLK to EN): no restart. Check that wire.")
    if all(v == "silent" for v, _, _ in found):
        return "Nothing heard at all.", ["Is the ESP32 running the wiring test firmware?",
                                         "(tools/wifi/flash_esp.sh esp32 PORT --wiretest)", "Power: 3.3 V, and the ground wire between the boards."]
    return ("All 7 wires are right." if not bad else "%d wire%s to fix." % (bad, "s" if bad > 1 else "")), lines


# ---------------------------------------------------------------- Linux's GPIO character device (v2)
class _Attr(ctypes.Structure): _fields_ = [("id", ctypes.c_uint32), ("padding", ctypes.c_uint32), ("values", ctypes.c_uint64)]
class _CfgAttr(ctypes.Structure): _fields_ = [("attr", _Attr), ("mask", ctypes.c_uint64)]
class _Config(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("num_attrs", ctypes.c_uint32), ("padding", ctypes.c_uint32 * 5), ("attrs", _CfgAttr * 10)]
class _Request(ctypes.Structure):
    _fields_ = [("offsets", ctypes.c_uint32 * 64), ("consumer", ctypes.c_char * 32), ("config", _Config), ("num_lines", ctypes.c_uint32),
                ("event_buffer_size", ctypes.c_uint32), ("padding", ctypes.c_uint32 * 5), ("fd", ctypes.c_int32)]
class _Values(ctypes.Structure): _fields_ = [("bits", ctypes.c_uint64), ("mask", ctypes.c_uint64)]
def _iowr(nr, size): return (3 << 30) | (size << 16) | (0xB4 << 8) | nr
GET_LINE, GET_VALUES, SET_VALUES = _iowr(0x07, ctypes.sizeof(_Request)), _iowr(0x0E, ctypes.sizeof(_Values)), _iowr(0x0F, ctypes.sizeof(_Values))
F_INPUT, F_OUTPUT, F_PULL_DOWN = 1 << 2, 1 << 3, 1 << 9


def _lines(offsets, flags, name="wiretest"):
    """A request for these lines (input with pull-down, or output): its fd."""
    r = _Request(); r.consumer = name.encode(); r.config.flags = flags; r.num_lines = len(offsets)
    for i, o in enumerate(offsets): r.offsets[i] = o
    with open("/dev/gpiochip0", "rb", buffering=0) as chip: fcntl.ioctl(chip.fileno(), GET_LINE, r)
    return r.fd


def _read(fd, n):
    v = _Values(); v.mask = (1 << n) - 1; fcntl.ioctl(fd, GET_VALUES, v); return v.bits


def _sh(*cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)


def run(seconds=2.0):
    """The test on the board: (headline, lines). The WiFi is stopped for it and started again after.
    (VACATION_WIRETEST_FAKE on a desktop: a made-up result, MISO and clock swapped, to see the page.)"""
    if os.environ.get("VACATION_WIRETEST_FAKE"):
        time.sleep(1.5)
        return report([("right", "TDO (IO15)", 5), ("right", "TCK (IO13)", 7), ("swapped", "TDI (IO12)", 13), ("swapped", "TMS (IO14)", 11),
                       ("right", "IO2", 17), ("silent", None, None)], True)
    _sh("/etc/init.d/S35wifi", "stop")
    unbound = os.path.exists(os.path.join(SPI_DRIVER, SPI_DEV))
    if unbound:
        with open(os.path.join(SPI_DRIVER, "unbind"), "w") as f: f.write(SPI_DEV)
    try:
        fd = _lines([w[2] for w in WIRES], F_INPUT | F_PULL_DOWN)
        try:
            times, levels = [], [[] for _ in WIRES]
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:                      # (about 1 kHz: the rhythms are 5 to 19 ms)
                bits = _read(fd, len(WIRES)); times.append(time.monotonic() - t0)
                for i in range(len(WIRES)): levels[i].append((bits >> i) & 1)
                time.sleep(0.0007)
            found = analyse(times, levels)
            reset = None
            if any(v != "silent" for v, _, _ in found):                 # (the reset wire: does the ESP restart?)
                rfd = _lines([RESET[2]], F_OUTPUT)
                try:
                    v = _Values(); v.mask = 1; v.bits = 0; fcntl.ioctl(rfd, SET_VALUES, v)     # (EN low: held in reset)
                    time.sleep(0.15)
                finally: os.close(rfd)                                   # (let go: EN pulled up, it boots)
                changes, t1, last = 0, time.monotonic(), _read(fd, len(WIRES))
                while time.monotonic() - t1 < 0.25:                      # (just after: a restarting ESP is silent)
                    b = _read(fd, len(WIRES)); changes += b != last; last = b; time.sleep(0.001)
                reset = changes <= 2                                    # (running, it would change ~50 times in that time)
        finally: os.close(fd)
    finally:
        if unbound:
            with open(os.path.join(SPI_DRIVER, "bind"), "w") as f: f.write(SPI_DEV)
        _sh("/etc/init.d/S35wifi", "start")
    return report(found, reset)
