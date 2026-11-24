#!/usr/bin/env python3
"""Pack, sign and install a vacation-countdown module on the board, over USB, in one go.

    tools/board/deploy_module.py [--key KEY] [--force] [--use] NAME      (NAME: castle, cruise, ...)

1. tools/modules/pack.py: the tarball and its signed statement (OpenSSL asks for the key's passphrase;
   KEY default: ~/.config/licheepi-nano/module-signing.pem, from tools/modules/keygen.sh);
2. the app stopped (the board drops bytes when it's busy, and modinstall is quicker alone), and both
   files to the board's /apps/data/modules/ (push_to_board.py);
3. modinstall there (checks the signature against the board's trusted keys, installs; --force: even an
   older version), waiting for it to finish;
4. with --use, the countdown switched to it (MODULE=NAME in its vacation.conf; otherwise it shows the
   module it showed before);
5. the copies removed, and the app started again (whatever happened).

The board needs a base system with modinstall and your key (tools/build/build.sh after keygen.sh,
then tools/board/flash_sd.sh build/images). For trying changes without signing: deploy_app.py vacation.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(REPO, "tools", "modules"))
REMOTE = "/apps/data/modules"
CONF = "/apps/data/vacation/vacation.conf"
DEFAULT_KEY = os.path.expanduser("~/.config/licheepi-nano/module-signing.pem")


def on_board(port, command, secs):
    """Run a shell command on the board; wait (up to secs) for it to finish: (exit status, output)."""
    import boardlib
    port.reset_input_buffer()
    port.write(('%s; echo "__MOD""DONE $?"\n' % command).encode())       # (split: the echoed command doesn't match)
    out = boardlib.read_until(port, b"__MODDONE ", secs)
    out += boardlib.read_until(port, b"\n", 2)
    text = out.decode("utf-8", "replace").replace("\r", "")
    if "__MODDONE " not in text: return None, text
    body, status = text.rsplit("__MODDONE ", 1)
    lines = body.split("\n")[1:]                                               # (the echoed command)
    return int(status.split()[0]), "\n".join(l for l in lines if l.strip()).strip()


def main():
    sys.stdout.reconfigure(line_buffering=True)                               # (in order with the tools it runs)
    a = sys.argv[1:]
    key = a[a.index("--key") + 1] if "--key" in a else DEFAULT_KEY
    if "--key" in a: i = a.index("--key"); del a[i:i + 2]
    force, use = "--force" in a, "--use" in a
    names = [x for x in a if not x.startswith("-")]
    if len(names) != 1 or len(names) != len(a) - force - use: sys.exit(__doc__)
    name = names[0]
    if not os.path.isdir(os.path.join(REPO, "vacation", "modules", name)): sys.exit("no module %s in vacation/modules/" % name)
    if not os.path.exists(key): sys.exit("no signing key at %s (tools/modules/keygen.sh makes one; --key KEY)" % key)
    try: import serial                                                          # (before asking for the passphrase)
    except ImportError: sys.exit("%s has no pyserial: pip install -r tools/requirements.txt (in a virtualenv: see docs/tools.md)" % sys.executable)

    import pack
    tar = pack.pack(name, key)
    files = [os.path.basename(tar), os.path.basename(tar) + ".sig"]
    pairs = []
    for f in files: pairs += [os.path.join(os.path.dirname(tar), f), "%s/%s" % (REMOTE, f)]
    import boardlib
    def board(command, secs):
        port = boardlib.open_port(timeout=0.2)
        try:
            boardlib.login(port)
            return on_board(port, command, secs)
        finally:
            port.close()                                                        # (push_to_board.py opens it too)

    board("/etc/init.d/S99app stop >/dev/null 2>&1", 60)
    print("stopped the app")
    try:
        if subprocess.run([sys.executable, os.path.join(HERE, "push_to_board.py"), "--keep-running", *pairs]).returncode:
            sys.exit("copying to the board failed")
        status, out = board("cd %s && modinstall %s%s" % (REMOTE, "--force " if force else "", files[0]), 300)
        print(out)
        if status is None: sys.exit("modinstall didn't finish in 5 minutes (still running?)")
        if status:
            if "no trusted keys" in out or "isn't trusted" in out:
                print("(the board doesn't trust this key: a different key from the one in its base system, or a base system"
                      " from before the key: tools/build/build.sh, then tools/board/flash_sd.sh build/images)")
            sys.exit(1)
        if use:
            board("grep -q '^MODULE=' %s && sed -i 's/^MODULE=.*/MODULE=%s/' %s || echo MODULE=%s >> %s"
                  % (CONF, name, CONF, name, CONF), 30)
            print("the countdown now shows %s (MODULE=%s)" % (name, name))
        else:
            print("(the countdown shows the module it showed before: --use switches to this one)")
    finally:
        board("cd / && rm -f %s; /etc/init.d/S99app start >/dev/null 2>&1" % " ".join("%s/%s" % (REMOTE, f) for f in files), 60)
        print("started the app")

if __name__ == "__main__":
    main()
