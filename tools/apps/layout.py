#!/usr/bin/env python3
"""An app's files as they go on the board, laid out in a folder: the one rule the SD card image,
tools/board/deploy.py and tools/apps/pack.py all use.

    tools/apps/layout.py [--local] NAME [DEST]    (DEST default: build/apps/NAME; NAME: a folder in apps/)

An app with an install.sh lays itself out (`install.sh DEST`): the system package (it compiles its
drawing library: for the board, in the build container, with CC set to the board's compiler) and the
chess clock. Any other app is its folder as it is, less its tools/ (desktop helpers), Python caches,
and what its app.json "exclude" lists (paths in it, * allowed); and its "native" programs compiled
into it: [{"src": "aisd.c", "out": "aisd", "libs": "-lssl -lcrypto"}] (for the board in the WiFi build
tree, which has OpenSSL; on a Mac, against Homebrew's).

The board's compiler comes from tools/build/build.sh's build tree (its licheepi-out volume, with the
base image licheepi-nano-mybase) when that's there; otherwise from DEV_IMAGE (default
licheepi-nano-dev: the Dockerfile's fast build, tagged as its top comment says). Apple's `container`,
or else Docker. --local: no container: $CC (default cc, the desktop's own) compiles, for the Mac or inside the build itself.
"""
import fnmatch, json, os, shutil, subprocess, sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS = os.path.join(REPO, "apps")
SKIP_DIRS = {"tools", "__pycache__", ".git"}
SKIP_FILES = ["*.pyc", ".DS_Store"]
BOARD_CC = "/root/buildroot/output/host/bin/arm-linux-gcc"


def manifest(name):
    return json.load(open(os.path.join(APPS, name, "app.json")))


def files(name):
    """An app's files that go on the board, for an app without an install.sh: [(path in the app, path here)]."""
    root = os.path.join(APPS, name)
    exclude = manifest(name).get("exclude", [])
    def excluded(rel):
        return any(fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("/") + "/") for pat in exclude)
    out = []
    for d, dirs, fs in os.walk(root):
        rel_dir = os.path.relpath(d, root)
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not excluded(os.path.normpath(os.path.join(rel_dir, x))))
        for f in fs:
            rel = os.path.normpath(os.path.join(rel_dir, f))
            if any(fnmatch.fnmatch(f, pat) for pat in SKIP_FILES) or excluded(rel): continue
            out.append((rel, os.path.join(d, f)))
    return sorted(out)


def _in_container(name, script):
    """Run a shell script in the build container (the board's compiler as $CC), the repository at /src. The
    WiFi build tree when there is one (a superset: it has OpenSSL too), else the plain one."""
    runner = shutil.which("container") or shutil.which("docker")
    if not runner: sys.exit("needs Apple's container tool or Docker, to compile %s for the board" % name)
    volume = None
    if os.path.basename(runner) == "container" and "DEV_IMAGE" not in os.environ:
        for v in ("licheepi-out-wifi", "licheepi-out"):
            if subprocess.run([runner, "volume", "inspect", v], capture_output=True).returncode == 0: volume = v; break
    where = (["-v", "%s:/root/buildroot" % volume, os.environ.get("BASE_IMAGE", "licheepi-nano-mybase")] if volume
             else [os.environ.get("DEV_IMAGE", "licheepi-nano-dev")])
    r = subprocess.run([runner, "run", "--rm", "-v", "%s:/src" % REPO] + where + ["sh", "-c", "CC=%s; %s" % (BOARD_CC, script)],
                       stdout=subprocess.DEVNULL)
    if r.returncode:
        sys.exit("compiling %s failed (%s)" % (name, "the build tree: run tools/build/build.sh once" if volume
                                               else "is the build image there? see the Dockerfile's top comment"))


def _native(name, dest, board):
    """Compile the app's "native" programs into dest."""
    for n in manifest(name).get("native", []):
        src = os.path.join(APPS, name, n["src"]); libs = n.get("libs", "")
        if board:
            rel = os.path.relpath(dest, REPO)
            _in_container(name, "$CC -O2 -Wall -o /src/%s/%s /src/apps/%s/%s %s" % (rel, n["out"], name, n["src"], libs))
        else:
            extra = []
            if sys.platform == "darwin" and "ssl" in libs:          # (Homebrew's OpenSSL)
                o = "/opt/homebrew/opt/openssl@3"; extra = ["-I" + o + "/include", "-L" + o + "/lib"]
            r = subprocess.run([os.environ.get("CC", "cc"), "-O2", "-Wall", *extra, "-o", os.path.join(dest, n["out"]), src, *libs.split()])
            if r.returncode: sys.exit("compiling %s's %s failed" % (name, n["src"]))


def _container_install(name, dest):
    """Run the app's install.sh in the build container (the board's compiler), into dest (under the repo)."""
    rel = os.path.relpath(dest, REPO)
    if rel.startswith(".."): sys.exit("laying out %s for the board: DEST must be inside the repository" % name)
    _in_container(name, "CC=$CC /src/apps/%s/install.sh /src/%s" % (name, rel))


def layout(name, dest=None, board=True):
    """Lay out apps/NAME into dest (default build/apps/NAME); returns dest."""
    src = os.path.join(APPS, name)
    if not os.path.isfile(os.path.join(src, "app.json")): sys.exit("no app %s (apps/%s/app.json)" % (name, name))
    dest = os.path.abspath(dest or os.path.join(REPO, "build", "apps", name))
    script = os.path.join(src, "install.sh")
    if os.path.isfile(script):
        if board and "CC" in open(script).read(): _container_install(name, dest)
        else:
            r = subprocess.run(["sh", script, dest], env=dict(os.environ, CC=os.environ.get("CC", "cc")))
            if r.returncode: sys.exit("%s's install.sh failed" % name)
    else:
        shutil.rmtree(dest, ignore_errors=True)
        for rel, path in files(name):
            out = os.path.join(dest, rel); os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(path, out)
        _native(name, dest, board)
    return dest


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if x != "--local"]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    print("laid out %s in %s" % (a[0], os.path.relpath(layout(a[0], a[1] if len(a) > 1 else None, "--local" not in sys.argv), REPO)))
