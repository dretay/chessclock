#!/usr/bin/env python3
"""Put an app on the board over the serial console, without reflashing (see docs/apps.md).

usage: deploy_app.py [--use] [--force] NAME        NAME: chess or vacation
       --use    also make it the app that runs (now and at every boot)
       --force  send every file, not just the changed ones

The app is laid out by its own install.sh in the build container (which has the board's C
compiler), into build/apps/NAME, then copied to /apps/NAME with push_to_board.py: only files that
changed go, and the running app is stopped meanwhile and started again after. Its settings
(/apps/data/NAME) aren't touched. Files deleted from the app aren't deleted on the board.
Fastest with the board's micro-USB port plugged into the Mac (used by itself when it's there);
over UART0, tools/fast_serial.py first, then CLOCK_BAUD=1562500.

The compiler comes from tools/build.sh's build tree (its licheepi-out volume, with the base image
licheepi-nano-mybase) when that's there; otherwise from DEV_IMAGE (default licheepi-nano-dev: the
Dockerfile's fast build, tagged as its top comment says). Apple's `container`, or else Docker.
"""
import os
import shutil
import subprocess
import sys

APPS = {"chess": "clock", "vacation": "vacation"}       # name on the board -> folder here
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
IMAGE = os.environ.get("DEV_IMAGE", "licheepi-nano-dev")
CC = "/root/buildroot/output/host/bin/arm-linux-gcc"

args = sys.argv[1:]
use, force = "--use" in args, "--force" in args
names = [a for a in args if not a.startswith("--")]
if len(names) != 1 or names[0] not in APPS:
    sys.exit(__doc__)
name = names[0]

runner = shutil.which("container") or shutil.which("docker")
if not runner:
    sys.exit("needs Apple's container tool or Docker, to compile for the board")
stage = "build/apps/" + name
# tools/build.sh's build tree has the compiler: use it if it's there (no separate image needed)
use_volume = os.path.basename(runner) == "container" and "DEV_IMAGE" not in os.environ and \
    subprocess.run([runner, "volume", "inspect", "licheepi-out"], capture_output=True).returncode == 0
where = ["-v", "licheepi-out:/root/buildroot", os.environ.get("BASE_IMAGE", "licheepi-nano-mybase")] if use_volume else [IMAGE]
r = subprocess.run([runner, "run", "--rm", "-v", "%s:/src" % REPO] + where + ["sh", "-c",
                    "CC=%s /src/%s/install.sh /src/%s" % (CC, APPS[name], stage)])
if r.returncode:
    sys.exit("laying out %s failed (%s)" % (name, "the build tree: run tools/build.sh once" if use_volume
                                             else "is the %s image there? see the Dockerfile's top comment" % IMAGE))
print("laid out %s in %s" % (name, stage))

push = [sys.executable, os.path.join(TOOLS, "push_to_board.py")] + (["--force"] if force else [])
if subprocess.run(push + [os.path.join(REPO, stage), "/apps/" + name]).returncode:
    sys.exit(1)
if use:
    subprocess.run([sys.executable, os.path.join(TOOLS, "run_on_board.py"), "--wait", "10", "app " + name])
