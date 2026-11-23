"""WiFi for Settings > WiFi: scan, join, forget, and what's connected (wlan0, from the ESP32 on SPI;
see package/esp-hosted).

Talks to wpa_supplicant over its control socket (/var/run/wpa_supplicant/wlan0), the way wpa_cli
does, so nothing else has to start: on the 32 MB board a separate program costs more than this.
Networks are saved in /etc/wpa_supplicant.conf by wpa_supplicant itself (SAVE_CONFIG); the
password is stored as its hashed key (PSK), never as typed.

VACATION_WIFI_FAKE=1: pretend (a few made-up networks), for previews on a desktop.
"""
import hashlib, os, socket, struct, tempfile, time

IFACE = "wlan0"
CTRL = "/var/run/wpa_supplicant/" + IFACE


class WifiError(Exception):
    pass


def present():
    """Whether there's WiFi hardware at all (the ESP32 answered and wlan0 exists)."""
    return bool(os.environ.get("VACATION_WIFI_FAKE")) or os.path.isdir("/sys/class/net/" + IFACE)


def psk_for(ssid, password):
    """WPA's hashed key for a network and its password (what wpa_passphrase works out)."""
    return hashlib.pbkdf2_hmac("sha1", password.encode(), ssid.encode(), 4096, 32).hex()


def ip_address():
    """wlan0's IPv4 address, or None."""
    try:
        import fcntl
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", IFACE.encode()))[20:24])   # SIOCGIFADDR
        finally: s.close()
    except OSError:
        return None


class Wpa:
    """A connection to wpa_supplicant's control socket."""

    def __init__(self):
        self.sock = None

    def _open(self):
        if self.sock: return
        if not os.path.exists(CTRL): raise WifiError("wpa_supplicant isn't running")
        self.local = os.path.join(tempfile.gettempdir(), "vacation_wpa_%d" % os.getpid())
        try: os.unlink(self.local)
        except OSError: pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(self.local); s.connect(CTRL); s.settimeout(3.0)
        self.sock = s

    def cmd(self, text):
        self._open()
        self.sock.send(text.encode())
        while True:
            reply = self.sock.recv(8192).decode("utf-8", "replace")
            if not reply.startswith("<"): return reply           # (skip unsolicited event messages)

    def ok(self, text):
        r = self.cmd(text)
        if not r.startswith("OK"): raise WifiError("%s: %s" % (text.split()[0], r.strip()))

    def close(self):
        if self.sock:
            self.sock.close(); self.sock = None
            try: os.unlink(self.local)
            except OSError: pass

    # ---------------------------------------------------------------- what Settings uses
    def scan(self, wait=4.0):
        """Networks in range: [(ssid, signal 0..4, secured)], strongest first, one line per name."""
        try: self.cmd("SCAN")                                      # ("FAIL-BUSY" if one's running: fine)
        except OSError: pass
        end = time.time() + wait
        while time.time() < end: time.sleep(0.25)
        best = {}
        for line in self.cmd("SCAN_RESULTS").splitlines()[1:]:    # bssid / frequency / signal level / flags / ssid
            f = line.split("\t")
            if len(f) < 5 or not f[4] or f[4].startswith("\\x00"): continue   # (hidden networks)
            ssid = decode_ssid(f[4])
            try: dbm = int(f[2])
            except ValueError: continue
            secured = any(k in f[3] for k in ("WPA", "WEP", "SAE"))
            if ssid not in best or dbm > best[ssid][0]: best[ssid] = (dbm, secured)
        nets = sorted(best.items(), key=lambda kv: -kv[1][0])
        return [(ssid, bars(dbm), sec) for ssid, (dbm, sec) in nets]

    def status(self):
        """(state, ssid): state is "connected", "connecting" or "off"."""
        st = dict(l.split("=", 1) for l in self.cmd("STATUS").splitlines() if "=" in l)
        state = st.get("wpa_state", "")
        if state == "COMPLETED": return "connected", decode_ssid(st.get("ssid", ""))
        if state in ("ASSOCIATING", "ASSOCIATED", "AUTHENTICATING", "4WAY_HANDSHAKE", "GROUP_HANDSHAKE", "SCANNING"):
            return "connecting", decode_ssid(st.get("ssid", ""))
        return "off", ""

    def join(self, ssid, password):
        """Forget other networks, add this one (password None: an open network), connect, and save."""
        self.forget(save=False)
        nid = self.cmd("ADD_NETWORK").strip()
        if not nid.isdigit(): raise WifiError("ADD_NETWORK: " + nid)
        self.ok("SET_NETWORK %s ssid %s" % (nid, ssid.encode().hex()))   # (hex: no quoting troubles)
        if password: self.ok("SET_NETWORK %s psk %s" % (nid, psk_for(ssid, password)))
        else: self.ok("SET_NETWORK %s key_mgmt NONE" % nid)
        self.ok("ENABLE_NETWORK %s" % nid)
        self.ok("SELECT_NETWORK %s" % nid)
        self.ok("SAVE_CONFIG")

    def forget(self, save=True):
        self.ok("REMOVE_NETWORK all")
        if save: self.ok("SAVE_CONFIG")


def decode_ssid(s):
    """wpa_supplicant's printf-escaped SSID text back to a string."""
    try: return s.encode("latin-1").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    except (UnicodeDecodeError, UnicodeEncodeError): return s


def bars(dbm):
    return 4 if dbm >= -55 else 3 if dbm >= -65 else 2 if dbm >= -75 else 1 if dbm >= -85 else 0


class FakeWpa:
    """For previews: a few networks, and joining works with any password but "wrong"."""
    def __init__(self): self.joined = None; self.joined_at = 0.0

    def scan(self, wait=4.0):
        return [("Tayman Home", 4, True), ("Tayman Guest", 3, True), ("xfinitywifi", 2, False),
                ("NETGEAR42", 1, True), ("DIRECT-HP OfficeJet", 1, True), ("Neighbor 5G", 0, True)]

    def status(self):
        if not self.joined: return "off", ""
        self.polls = getattr(self, "polls", 0) + 1                    # (a preview's clock isn't real time)
        return ("connected" if self.polls > 2 else "connecting"), self.joined

    def join(self, ssid, password):
        if password == "wrong": raise WifiError("couldn't connect")
        self.joined, self.joined_at, self.polls = ssid, time.time(), 0

    def forget(self, save=True): self.joined = None

    def close(self): pass


def connect():
    return FakeWpa() if os.environ.get("VACATION_WIFI_FAKE") else Wpa()


def fake_ip():
    return "192.168.1.42" if os.environ.get("VACATION_WIFI_FAKE") else None
