"""What every app and the system screens share: the apps installed, their manifests, the settings files
(KEY=VALUE lines), and the device's own settings (/apps/data/device.conf: touch calibration, brightness,
CPU clock, the catalog's address), which the countdown, the picker and Device settings
all read, and write.
"""
import json, os


# the device's own settings, shared by every app: /apps/data/device.conf (the countdown
# and the app picker read them from there, and write them there)
DEVICE_CONF = "device.conf"


DEVICE_KEYS = ("TOUCH_X_MIN", "TOUCH_X_MAX", "TOUCH_Y_MIN", "TOUCH_Y_MAX", "TOUCH_SWAP_XY", "DAY_BRIGHTNESS",
               "NIGHT_BRIGHTNESS", "NIGHT_START", "NIGHT_END", "CPU_MHZ", "CATALOG_URL")


def read_conf(path):
    """KEY=VALUE lines (# comments), as a dict; empty if the file isn't there."""
    conf = {}
    try:
        for line in open(path):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1); conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def device_path(data_dir):
    """The device's settings file: beside the apps' own data folders (/apps/data/device.conf)."""
    return os.path.join(os.path.dirname(os.path.abspath(data_dir)), DEVICE_CONF)


def read_settings(conf_path, device=None):
    """An app's settings, with the device's (device.conf) in place of its own copies of those keys."""
    conf = read_conf(conf_path)
    if device:
        conf.update({k: v for k, v in read_conf(device).items() if k in DEVICE_KEYS})
    return conf


def manifest_path(app_dir):
    for name in ("app.json", "module.json"):
        p = os.path.join(app_dir, name)
        if os.path.isfile(p): return p
    return None


def installed(root="/apps"):
    """Every app in root that can be started (has a run), for the picker: [(id, name, folder)], by name."""
    out = []
    for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, d)
        if d.startswith(".") or not os.access(os.path.join(p, "run"), os.X_OK): continue
        name = d
        mp = manifest_path(p)
        if mp:
            try:
                meta = json.load(open(mp))
                if meta.get("kind") == "runtime": continue
                name = meta.get("name", d)
            except (OSError, ValueError): pass
        out.append((d, name, p))
    return sorted(out, key=lambda a: a[1].lower())
