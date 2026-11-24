"""Get apps: the signed app catalog, for the app picker (picker.py).

tools/apps/publish.py publishes each app (its tarball and signed statement) as a GitHub release, and
catalog.json beside them, itself signed (catalog.json.sig, a statement like an app's), under the release
tag "catalog". On the board: download catalog.json and its .sig, check them with modinstall (signed by a
trusted key; the file is the one signed), then each app's status against what's installed; installing
downloads the app's files and hands them to modinstall (which checks them again, and refuses what it
should), its runtime first if that's missing or too old. Downloads go to /apps/data/packages, removed
after. CATALOG_URL in the device's settings (/apps/data/device.conf) points elsewhere.
"""
import json, os, ssl, subprocess, urllib.request

DEFAULT_URL = "https://github.com/dretay/chessclock/releases/download/catalog/catalog.json"
CA_FILE = "/etc/ssl/certs/ca-certificates.crt"           # (Buildroot's ca-certificates)
MODINSTALL = os.environ.get("MODINSTALL", "modinstall")


class CatalogError(Exception):
    pass


def ctx():
    return ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)


def fetch(url, dest, progress=None):
    """Download url to dest (through dest.part), calling progress(fraction) as it goes."""
    req = urllib.request.Request(url, headers={"User-Agent": "licheepi-app-catalog"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx()) as r, open(dest + ".part", "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                chunk = r.read(32768)
                if not chunk: break
                f.write(chunk); done += len(chunk)
                if progress and total: progress(done / total)
    except (OSError, ValueError) as e:
        try: os.remove(dest + ".part")
        except OSError: pass
        raise CatalogError("couldn't download %s: %s" % (os.path.basename(dest), e))
    os.replace(dest + ".part", dest)


def modinstall(*args, root="/apps"):
    r = subprocess.run([MODINSTALL, "--dir", root, *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines() or [""]


def load(url, work):
    """The catalog, checked: {"apps": [...]}; raises CatalogError."""
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, "catalog.json")
    fetch(url, path); fetch(url + ".sig", path + ".sig")
    code, out = modinstall("--check", path, path + ".sig")
    if code: raise CatalogError("the catalog doesn't check out (changed, or not signed by a key this board trusts): %s"
                                % out[-1].replace("modinstall: ", ""))
    try: return json.load(open(path))
    except ValueError: raise CatalogError("the catalog is damaged")


def vtuple(v):
    try: return tuple(int(x) for x in str(v).split("."))
    except ValueError: return (0,)


def installed_version(root, app_id):
    """The installed version (from its .signature, else its app.json), or None."""
    d = os.path.join(root, app_id)
    try:
        for line in open(os.path.join(d, ".signature")):
            if line.startswith("version "): return line.split(None, 1)[1].strip()
    except OSError: pass
    try: return json.load(open(os.path.join(d, "app.json"))).get("version")
    except (OSError, ValueError): return None


def status(entry, root):
    """"Install", "Update" or "Installed"."""
    have = installed_version(root, entry["id"])
    if have is None: return "Install"
    return "Update" if vtuple(entry["version"]) > vtuple(have) else "Installed"


def runtime_api(root, runtime):
    try: return int(open(os.path.join(root, runtime, "API")).read().strip())
    except (OSError, ValueError): return -1


def install(entry, catalog, root, work, progress=None, say=None):
    """Download and install one app (its runtime first if it needs it); returns modinstall's last line."""
    rt = entry.get("runtime")
    if rt and runtime_api(root, rt) < entry.get("api", 0):
        dep = next((a for a in catalog.get("apps", []) if a["id"] == rt), None)
        if not dep: raise CatalogError("%s needs the %s runtime, and the catalog hasn't got it" % (entry["name"], rt))
        install(dep, catalog, root, work, progress, say)
    if say: say("Downloading %s" % entry["name"])
    os.makedirs(work, exist_ok=True)
    tar = os.path.join(work, os.path.basename(entry["url"]))
    try:
        fetch(entry["url"], tar, progress)
        fetch(entry["sig"], tar + ".sig")
        if say: say("Installing %s" % entry["name"])
        code, out = modinstall(tar, tar + ".sig", root=root)
    finally:
        for f in (tar, tar + ".sig"):
            try: os.remove(f)
            except OSError: pass
    if code: raise CatalogError(out[-1].replace("modinstall: ", ""))
    return out[0]
