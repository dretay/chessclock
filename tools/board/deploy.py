#!/usr/bin/env -S uv run -q python
"""Put apps on the board over USB (see docs/apps.md), without reflashing.

    tools/board/deploy.py [--signed [--key KEY] [--passphrase-stdin]] [--use NAME] [--force] NAME [NAME ...]
    e.g. tools/board/deploy.py castle                       (quick: the files that changed, unsigned)
         tools/board/deploy.py --signed countdown castle    (packed, signed, installed by modinstall)
         tools/board/deploy.py --use cruise cruise          (... and switch to it)

NAME: an app in apps/ (chess, countdown: the countdown runtime, castle, cruise). Each is laid out by
tools/apps/layout.py (compiled for the board in the build container where it needs it).

- Without --signed (the developer's way): copied to /apps/NAME with push_to_board.py, only the files
  that changed (--force: all of them; files deleted from the app stay on the board). No signature:
  an app installed this way has no .signature, and the next signed install says "was an unsigned copy".
- --signed: packed and signed (tools/apps/pack.py; OpenSSL asks for the key's passphrase once; KEY
  default ~/.config/licheepi-nano/module-signing.pem from tools/apps/keygen.sh), copied to
  /apps/data/packages, and installed by the board's modinstall (--passphrase-stdin: the passphrase as
  one line on stdin instead, for the previewer's Install button; never on a command line or in the
  environment) (it checks the signature against the
  board's trusted keys; --force: even an older version). A runtime goes before the apps on it.

The app that's running is stopped first (the board drops bytes when it's busy) and started again at
the end, whatever happened; --use NAME makes NAME the one that runs (now and at every boot).
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(REPO, "tools", "apps"))
PACKAGES = "/apps/data/packages"
DEFAULT_KEY = os.path.expanduser("~/.config/licheepi-nano/module-signing.pem")


def on_board(port, command, secs):
    """Run a shell command on the board; wait (up to secs) for it to finish: (exit status, output)."""
    import boardlib
    port.reset_input_buffer()
    port.write(('%s; echo "__DEP""DONE $?"\n' % command).encode())       # (split: the echoed command doesn't match)
    out = boardlib.read_until(port, b"__DEPDONE ", secs)
    out += boardlib.read_until(port, b"\n", 2)
    text = out.decode("utf-8", "replace").replace("\r", "")
    if "__DEPDONE " not in text: return None, text
    body, status = text.rsplit("__DEPDONE ", 1)
    # the board echoes the command back, wrapped over as many lines as it takes: its output starts after
    # the command's end ($?")
    body = body.rsplit('$?"', 1)[1] if '$?"' in body else body.split("\n", 1)[-1]
    # (a wrap can split the command's end over two lines, leaving its closing quote on a line of its own)
    return int(status.split()[0]), "\n".join(l for l in body.split("\n") if l.strip() and l.strip() != '"').strip()


def board(command, secs=60):
    import boardlib
    port = boardlib.open_port(timeout=0.2)
    try:
        boardlib.login(port)
        return on_board(port, command, secs)
    finally:
        port.close()                                                        # (push_to_board.py opens it too)


def push(pairs, force=False):
    cmd = [sys.executable, os.path.join(HERE, "push_to_board.py"), "--keep-running"] + (["--force"] if force else []) + pairs
    if subprocess.run(cmd).returncode: sys.exit("copying to the board failed")


def main():
    sys.stdout.reconfigure(line_buffering=True)                               # (in order with the tools it runs)
    a = sys.argv[1:]
    def option(flag):
        if flag not in a: return None
        i = a.index(flag); v = a[i + 1] if i + 1 < len(a) else None; del a[i:i + 2]; return v
    key, use = option("--key"), option("--use")
    signed, force, pass_stdin = "--signed" in a, "--force" in a, "--passphrase-stdin" in a
    names = [x for x in a if not x.startswith("-")]
    if not names or len(names) != len(a) - signed - force - pass_stdin: sys.exit(__doc__)
    import layout
    for n in names:
        if not os.path.isfile(os.path.join(REPO, "apps", n, "app.json")): sys.exit("no app %s in apps/" % n)
    if use and not os.path.exists(os.path.join(REPO, "apps", use, "run")): sys.exit("--use %s: not an app that runs" % use)
    names.sort(key=lambda n: layout.manifest(n).get("kind") != "runtime")   # (a runtime before the apps on it)
    key = key or DEFAULT_KEY
    if signed and not os.path.exists(key): sys.exit("no signing key at %s (tools/apps/keygen.sh makes one; --key KEY)" % key)
    try: import serial                                                          # (before asking for the passphrase)
    except ImportError: sys.exit("%s has no pyserial: run it with uv run (tools/setup.sh; see docs/tools.md)" % sys.executable)

    if signed:
        import pack
        if pass_stdin:                                                         # (the previewer's: one line on stdin, not a prompt)
            pack._passphrases[key] = sys.stdin.readline().rstrip("\n")
        packages = [pack.pack(n, key) for n in names]
    else:
        staged = [layout.layout(n) for n in names]
        for n in names: print("laid out", n)

    if not signed:
        status, _ = board("[ -f /apps/data/locked ]", 30)
        if status == 0: sys.exit("the board only runs signed apps: --signed, or turn on Settings > Device > Developer on the board (or `app unlock`) first")
    board("/etc/init.d/S99app stop >/dev/null 2>&1")
    print("stopped the app")
    copied = []
    try:
        if not signed:
            pairs = []
            for n, d in zip(names, staged): pairs += [d, "/apps/" + n]
            push(pairs, force)
            # (what was signed isn't what's there now: an unsigned copy says so, until the next --signed)
            board("rm -f %s" % " ".join("/apps/%s/.signature" % n for n in names))
        else:
            pairs = []
            for t in packages:
                for f in (t, t + ".sig"):
                    pairs += [f, "%s/%s" % (PACKAGES, os.path.basename(f))]; copied.append("%s/%s" % (PACKAGES, os.path.basename(f)))
            push(pairs)
            for t in packages:
                status, out = board("cd %s && modinstall %s%s" % (PACKAGES, "--force " if force else "", os.path.basename(t)), 300)
                print(out)
                if status is None: sys.exit("modinstall didn't finish in 5 minutes (still running?)")
                if status:
                    if "no trusted keys" in out or "isn't trusted" in out:
                        print("(the board doesn't trust this key: a different key from the one in its base system, or a base system"
                              " from before the key: tools/build/build.sh, then tools/board/flash_sd.sh build/images)")
                    sys.exit(1)
        if use:
            board("echo %s > /apps/current.tmp && mv /apps/current.tmp /apps/current && sync" % use)
            print("the board now runs %s" % use)
    finally:
        cleanup = "rm -f %s; " % " ".join(copied) if copied else ""
        board("cd / && %s/etc/init.d/S99app start >/dev/null 2>&1" % cleanup)
        print("started the app")


if __name__ == "__main__":
    main()
