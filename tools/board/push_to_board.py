#!/usr/bin/env python3
"""Copy files (or folders) to the board over the serial console, near line speed.

usage: push_to_board.py [--keep-running] [--force] LOCAL REMOTE [LOCAL REMOTE ...]
e.g.   tools/board/push_to_board.py clock/fbclock.py /apps/chess/fbclock.py
       tools/board/push_to_board.py vacation/modules/cruise/map/tiles /apps/vacation/modules/cruise/map/tiles      (a folder)
(To update a whole app, tools/board/deploy_app.py does this for you.)
Fastest: the board's micro-USB port plugged into the Mac (used by itself when it's there, see
boardlib.py). Over UART0: tools/board/fast_serial.py, then CLOCK_BAUD=1562500 (13x the usual 115200).

Only what's changed is sent: files whose checksum already matches the board's are skipped
(--force sends them anyway); for a folder, just its new or changed files go, packed into one tar.
Nothing on the board is deleted.

Neither the console nor the board's USB serial port holds the sender back, so the board drops
bytes when it's busy or sent to too fast: the running app (the
chess clock or the vacation countdown) is stopped while copying and started again after, unless
--keep-running. Data goes as raw bytes (the board's terminal in raw mode) in 1 MB pieces,
each checked (md5) and sent again if it arrived damaged, then joined into place. The board only
starts reading once it has printed a marker, so the data never reaches the shell as commands.
"""
import hashlib
import io
import os
import sys
import tarfile
import time

import boardlib

PIECE = 1024 * 1024
TRIES = 4
APPS = ("/etc/init.d/S99app", "/etc/init.d/S99vacation", "/etc/init.d/S99fbclock")   # (and older images')
n_marker = [0]
# how fast to send: the line's own rate, or less when the board can't keep up (bytes a second),
# in bursts this big
# (USB: the board's USB serial port drops bytes rather than hold the Mac back when it can't keep
# up: about 1.1 MB/s was the most that arrived whole, with the app stopped)
RATE = float(os.environ.get("PUSH_RATE", 800 * 1024 if boardlib.USB else boardlib.BAUD / 10 * 0.96))
STEP = int(os.environ.get("PUSH_STEP", "1024"))


def shell(port, cmd, secs=30):
    """Run a command; returns its output (up to an end marker the shell computes, so the
    echoed command line can't match it)."""
    n_marker[0] += 1
    k = n_marker[0]
    port.write(("%s; echo END-%d-$((40+2))\n" % (cmd, k)).encode())
    out = boardlib.read_until(port, ("END-%d-42\r\n" % k).encode(), secs)
    return out.decode("utf-8", "replace")


def send_piece(port, data, dst):
    """One piece into dst as raw bytes; True if its checksum matches."""
    want = hashlib.md5(data).hexdigest()
    n_marker[0] += 1
    k = n_marker[0]
    port.reset_input_buffer()
    port.write(("stty raw -echo; echo GO-%d-$((40+2)); head -c %d > %s; stty -raw echo; echo GOT-%d-$((40+2))\n"
                % (k, len(data), dst, k)).encode())
    if ("GO-%d-42" % k).encode() not in boardlib.read_until(port, ("GO-%d-42" % k).encode(), 10):
        sys.exit("board did not start receiving; nothing sent")
    time.sleep(0.05)
    rate, step = RATE, STEP
    t0, sent = time.time(), 0
    while sent < len(data):
        port.write(data[sent:sent + step])
        sent += len(data[sent:sent + step])
        ahead = sent / rate - (time.time() - t0)
        if ahead > 0:
            time.sleep(ahead)
    done = ("GOT-%d-42" % k).encode()
    out = boardlib.read_until(port, done, 3)
    while done not in out:                            # bytes went missing: fill up what head is waiting for
        port.write(b"\0" * 256)
        out += boardlib.read_until(port, done, 0.5)
    if b"\0" in out or done not in out[-40:]:
        port.write(b"\x15")                          # (Ctrl-U: drop any filler the shell got)
    return want in shell(port, "md5sum %s" % dst, 30)


def push_bytes(port, raw, dst, label):
    t0 = time.time()
    pieces = [raw[i:i + PIECE] for i in range(0, len(raw), PIECE)] or [b""]
    tmp = dst if len(pieces) == 1 else "/tmp/xfer.part"
    for n, piece in enumerate(pieces):
        for attempt in range(TRIES):
            if send_piece(port, piece, tmp):
                break
            sys.stderr.write("\n  piece %d arrived damaged, sending again\n" % (n + 1))
        else:
            print("FAILED: %s" % label)
            return False
        if len(pieces) > 1:
            shell(port, "cat /tmp/xfer.part %s %s; rm /tmp/xfer.part" % (">" if n == 0 else ">>", dst))
        sys.stderr.write("\r  %3d%%" % (100 * (n + 1) // len(pieces)))
        sys.stderr.flush()
    ok = hashlib.md5(raw).hexdigest() in shell(port, "md5sum %s" % dst, 60)
    secs = time.time() - t0
    print("\r%s %s (%d bytes in %.0fs, %.0f KB/s)" % ("copied" if ok else "FAILED: checksum mismatch for", label,
                                                    len(raw), secs, len(raw) / 1024 / max(secs, 0.01)))
    return ok


def remote_sums(port, paths, folder=None):
    """path -> md5 for those that exist on the board (a folder: every file in it, relative)."""
    if folder:
        out = shell(port, "cd %s 2>/dev/null && find . -type f | xargs md5sum 2>/dev/null" % folder, 120)
    else:
        out = shell(port, "md5sum %s 2>/dev/null" % " ".join(paths), 60)
    sums = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 32:
            sums[parts[1][2:] if folder and parts[1].startswith("./") else parts[1]] = parts[0]
    return sums


def md5_file(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def folder_changes(port, src, dst, force):
    """The files in a local folder that aren't on the board as they are: [(relative, local path)]."""
    local = {}
    for root, _, files in os.walk(src):
        for f in files:
            if not f.startswith("."):
                p = os.path.join(root, f)
                local[os.path.relpath(p, src)] = p
    there = {} if force else remote_sums(port, None, dst)
    changed = [(r, local[r]) for r in sorted(local) if there.get(r) != md5_file(local[r])]
    print("%s: %s" % (dst, "%d of %d files to send" % (len(changed), len(local)) if changed else "all %d files already there" % len(local)))
    return changed


def push_folder(port, changed, dst):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for r, p in changed:
            tar.add(p, arcname=r)
    if not push_bytes(port, buf.getvalue(), "/root/xfer.tar", "%s (%d files)" % (dst, len(changed))):
        return False
    shell(port, "mkdir -p %s && tar -xf /root/xfer.tar -C %s; rm -f /root/xfer.tar" % (dst, dst), 120)
    return True


args = sys.argv[1:]
keep = "--keep-running" in args
force = "--force" in args
args = [a for a in args if a not in ("--keep-running", "--force")]
if not args or len(args) % 2:
    sys.exit(__doc__)
pairs = list(zip(args[0::2], args[1::2]))
for src, _ in pairs:
    if not os.path.exists(src):
        sys.exit("no such file: %s" % src)
port = boardlib.open_port()
boardlib.login(port)

files = [(s, d) for s, d in pairs if os.path.isfile(s)]
there = {} if force or not files else remote_sums(port, [d for _, d in files])
changes = {(s, d): folder_changes(port, s, d, force) for s, d in pairs if os.path.isdir(s)}
todo = [(s, d) for s, d in pairs if changes.get((s, d)) or (os.path.isfile(s) and there.get(d) != md5_file(s))]
for s, d in files:
    if (s, d) not in todo:
        print("unchanged: %s" % d)
if not todo:
    sys.exit(0)

stopped = []
if not keep:
    for app in APPS:
        if "RUN1NING" in shell(port, "[ -x %s ] && echo RUN$((1))NING" % app):
            shell(port, "%s stop >/dev/null 2>&1; sleep 1" % app, 20)      # (the app takes a moment to exit)
            stopped.append(app)
            print("stopped %s for the copying" % os.path.basename(app))
ok = True
try:
    for src, dst in todo:
        if os.path.isdir(src):
            ok = push_folder(port, changes[(src, dst)], dst) and ok
        else:
            shell(port, "mkdir -p %s" % os.path.dirname(dst))
            ok = push_bytes(port, open(src, "rb").read(), dst, dst) and ok
finally:
    for app in stopped:
        shell(port, "%s start >/dev/null 2>&1" % app, 20)
        print("started %s again" % os.path.basename(app))
sys.exit(0 if ok else 1)
