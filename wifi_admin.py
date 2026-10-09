#!/usr/bin/env python3
"""Restricted root Wi-Fi operations and startup fallback for Station."""
import fcntl, getpass, json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path

IFACE = "wlan0"
HELPER_API = "vipercoma-wifi-helper-v1"
AP_ID = "vipercoma-setup"
WIFI_DIR = Path("/etc/NetworkManager/system-connections")
AP_FILE = WIFI_DIR / "vipercoma-setup.nmconnection"
LOCK = Path("/run/lock/vipercoma-wifi.lock")
PENDING = Path("/run/vipercoma-wifi-connect.pending")
WRAPPER = "/usr/local/libexec/vipercoma-wifi-admin.py"

def run(args, *, timeout=45, check=True, input_text=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input_text)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Network command failed.").strip()[:240])
    return result

def ap_uuid():
    r = run(["/usr/bin/nmcli", "-g", "connection.uuid", "connection", "show", AP_ID], timeout=8, check=False)
    if r.returncode or not r.stdout.strip(): raise RuntimeError("Setup hotspot profile is missing.")
    return r.stdout.strip()

def escape_keyfile(value):
    slash = chr(92)
    return value.replace(slash, slash + slash).replace(chr(10), slash + "n").replace(chr(13), slash + "r")

def scan():
    r = run(["/usr/bin/nmcli", "--terse", "--escape", "yes", "--fields", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes", "ifname", IFACE], timeout=20)
    rows = {}
    for line in r.stdout.splitlines():
        cols, part, escaped = [], "", False
        for char in line:
            if escaped: part += char; escaped = False
            elif char == chr(92): escaped = True
            elif char == ":": cols.append(part); part = ""
            else: part += char
        cols.append(part)
        if len(cols) != 3 or not cols[0] or len(cols[0].encode("utf-8")) > 32: continue
        if any(ord(c) < 32 or ord(c) == 127 for c in cols[0]): continue
        try: signal = max(0, min(100, int(cols[1])))
        except ValueError: continue
        security = cols[2] or "Open"
        supported = not any(term in security.upper() for term in ("802.1X", "EAP", "WEP"))
        current = rows.get(cols[0])
        if current is None or signal > current["signal"]:
            rows[cols[0]] = {"ssid": cols[0], "signal": signal, "security": security, "supported": supported}
    return sorted(rows.values(), key=lambda x: (-x["signal"], x["ssid"]))[:100]

def saved_wifi_profiles():
    """Return saved, auto-connect infrastructure profiles without exposing secrets."""
    result = run(["/usr/bin/nmcli", "--terse", "--escape", "yes", "--fields", "UUID,TYPE", "connection", "show"], timeout=10)
    profiles = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2 or parts[1] != "802-11-wireless": continue
        ident = parts[0]
        if not ident or any(c not in "0123456789abcdef-" for c in ident.lower()): continue
        settings = run(["/usr/bin/nmcli", "-g", "802-11-wireless.ssid,connection.autoconnect,connection.autoconnect-priority,802-11-wireless.mode", "connection", "show", "uuid", ident], timeout=8, check=False)
        values = settings.stdout.splitlines()
        if settings.returncode or len(values) != 4: continue
        ssid, autoconnect, priority, mode = values
        if not ssid or autoconnect.lower() != "yes" or mode not in ("", "infrastructure"): continue
        try: priority = int(priority)
        except ValueError: priority = 0
        profiles.append({"uuid": ident, "ssid": ssid, "priority": priority})
    return profiles

def strongest_saved_profiles(networks=None, profiles=None):
    """Rank visible saved Wi-Fi profiles by strongest observed signal first."""
    networks = scan() if networks is None else networks
    profiles = saved_wifi_profiles() if profiles is None else profiles
    strongest = {}
    for network in networks:
        ssid = network.get("ssid")
        if isinstance(ssid, str): strongest[ssid] = max(strongest.get(ssid, -1), int(network.get("signal", 0)))
    candidates = [dict(profile, signal=strongest[profile["ssid"]])
                  for profile in profiles if profile.get("ssid") in strongest]
    return sorted(candidates, key=lambda profile: (-profile["signal"], -profile["priority"], profile["ssid"], profile["uuid"]))

def install_ap():
    existing = run(["/usr/bin/nmcli", "-g", "connection.uuid", "connection", "show", AP_ID], timeout=8, check=False)
    if existing.returncode == 0:
        ident = existing.stdout.strip()
        settings = run(["/usr/bin/nmcli", "-g", "802-11-wireless.mode,802-11-wireless.ssid,ipv4.method,ipv4.addresses,connection.autoconnect,802-11-wireless-security.key-mgmt", "connection", "show", "uuid", ident], timeout=8).stdout.splitlines()
        has_password = bool(run(["/usr/bin/nmcli", "--show-secrets", "-g", "802-11-wireless-security.psk", "connection", "show", "uuid", ident], timeout=8).stdout.strip())
        if len(settings) != 6 or settings[:4] != ["ap", "vipercoma-setup", "manual", "10.77.0.1/24"] or settings[4:] != ["no", "wpa-psk"] or not has_password:
            raise RuntimeError("Existing hotspot profile differs from the required isolated setup profile; nothing was changed.")
        print("Existing setup hotspot profile validated and preserved."); return
    password = getpass.getpass("Setup hotspot password (keep it private; it may match your Station password): ")
    if not 8 <= len(password) <= 63 or any(ord(c) < 32 or ord(c) > 126 for c in password): raise ValueError("Use 8–63 printable ASCII characters.")
    if password != getpass.getpass("Repeat password: "): raise ValueError("Passwords differ; nothing changed.")
    ident = str(uuid.uuid4())
    content = (
        "[connection]\nid=" + AP_ID + "\nuuid=" + ident + "\ntype=wifi\ninterface-name=" + IFACE + "\nautoconnect=false\n\n"
        "[wifi]\nmode=ap\nssid=vipercoma-setup\nband=bg\nchannel=6\n\n"
        "[wifi-security]\nkey-mgmt=wpa-psk\npsk=" + escape_keyfile(password) + "\n\n"
        "[ipv4]\nmethod=manual\naddress1=10.77.0.1/24\nnever-default=true\n\n[ipv6]\nmethod=disabled\n"
    )
    WIFI_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".vipercoma-setup-", dir=str(WIFI_DIR))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(content); f.flush(); os.fsync(f.fileno())
        os.replace(temp, AP_FILE)
        run(["/usr/bin/nmcli", "connection", "load", str(AP_FILE)], timeout=15)
        ap_uuid()
    except Exception:
        AP_FILE.unlink(missing_ok=True); raise
    print("Secured setup hotspot profile created.")

def connect(payload):
    if not isinstance(payload, dict) or set(payload) - {"ssid", "password"}:
        raise ValueError("Invalid Wi-Fi request.")
    ssid, password = payload.get("ssid"), payload.get("password")
    if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid): raise ValueError("Choose a valid visible Wi-Fi network.")
    if not isinstance(password, str) or len(password) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in password): raise ValueError("The Wi-Fi password is invalid.")
    if password and (len(password) < 8 or len(password) > 63): raise ValueError("Wi-Fi passwords must be 8–63 characters.")
    networks = {n["ssid"]: n for n in scan()}
    if ssid not in networks: raise ValueError("That network is no longer visible. Scan again.")
    if not networks[ssid].get("supported", True): raise ValueError("This network uses enterprise security that is not supported yet.")
    if ssid == "vipercoma-setup": raise ValueError("Choose your home or mobile Wi-Fi network.")
    if PENDING.exists(): raise ValueError("A Wi-Fi switch is already in progress.")
    ident = str(uuid.uuid4())
    profile = WIFI_DIR / ("vipercoma-wifi-" + ident + ".nmconnection")
    secure = "\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=" + escape_keyfile(password) if password else ""
    content = (
        "[connection]\nid=Station Wi-Fi " + ident[:8] + "\nuuid=" + ident + "\ntype=wifi\ninterface-name=" + IFACE + "\nautoconnect=false\nautoconnect-priority=50\n\n"
        "[wifi]\nmode=infrastructure\nssid=" + escape_keyfile(ssid) + "\n\n" + secure + "\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n"
    )
    WIFI_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".station-wifi-", dir=str(WIFI_DIR))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, profile)
        run(["/usr/bin/nmcli", "connection", "load", str(profile)], timeout=15)
        marker = PENDING.with_suffix(".tmp")
        marker.write_text(ident + "\n" + str(int(time.time()) + 150) + "\n")
        os.chmod(marker, 0o600); os.replace(marker, PENDING)
        run(["/usr/bin/systemd-run", "--unit=vipercoma-wifi-connect-" + ident[:8], "--on-active=3s", "--property=TimeoutStartSec=100s", "/usr/bin/python3", WRAPPER, "activate", ident], timeout=10)
    except Exception:
        run(["/usr/bin/nmcli", "connection", "delete", "uuid", ident], timeout=10, check=False)
        profile.unlink(missing_ok=True); PENDING.unlink(missing_ok=True); raise
    return {"ok": True, "message": "The Pi will join this network shortly. Join the same Wi-Fi on your phone; Station will then be at pihole.local:8080. Your Station sign-in password stays unchanged."}


def activate(ident):
    if not ident or any(c not in "0123456789abcdef-" for c in ident): raise ValueError("Invalid profile identifier.")
    profile = WIFI_DIR / ("vipercoma-wifi-" + ident + ".nmconnection")
    try:
        run(["/usr/bin/nmcli", "connection", "modify", "uuid", ident, "connection.autoconnect", "yes"], timeout=8)
        run(["/usr/bin/nmcli", "--wait", "60", "connection", "up", "uuid", ident, "ifname", IFACE], timeout=65)
        PENDING.unlink(missing_ok=True)
        print("Station Wi-Fi connected.", flush=True)
    except Exception:
        try:
            pending = PENDING.read_text().splitlines()
            if pending and pending[0] == ident: PENDING.unlink(missing_ok=True)
        except OSError: pass
        print("Wi-Fi connection failed; restoring setup hotspot.", flush=True)
        deleted = run(["/usr/bin/nmcli", "connection", "delete", "uuid", ident], timeout=10, check=False)
        if deleted.returncode:
            run(["/usr/bin/nmcli", "connection", "modify", "uuid", ident, "connection.autoconnect", "no"], timeout=8, check=False)
        profile.unlink(missing_ok=True)
        restored = run(["/usr/bin/nmcli", "--wait", "25", "connection", "up", "uuid", ap_uuid(), "ifname", IFACE], timeout=30, check=False)
        if restored.returncode:
            raise RuntimeError("Wi-Fi connection failed and the setup hotspot could not be restored yet.")


def active_wifi():
    r = run(["/usr/bin/nmcli", "-g", "GENERAL.TYPE,GENERAL.CONNECTION", "device", "show", IFACE], timeout=5, check=False)
    v = r.stdout.splitlines()
    if len(v) < 2 or v[1].strip() in {"", "--"}: return ""
    return v[1].strip()

def active_uuid():
    result = run(["/usr/bin/nmcli", "-g", "GENERAL.CON-UUID", "device", "show", IFACE], timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""

def prefer_strongest_saved_wifi():
    """Try visible saved profiles strongest first; return True once Wi-Fi is usable."""
    current_name = active_wifi()
    current_uuid = active_uuid()
    if current_name and current_name != AP_ID:
        # Preserve active hidden or manually-managed profiles that are not in a scan.
        try: candidates = strongest_saved_profiles()
        except (OSError, RuntimeError, subprocess.SubprocessError): return True
        if not any(profile["uuid"] == current_uuid for profile in candidates): return True
        if candidates and candidates[0]["uuid"] == current_uuid: return True
    else:
        try: candidates = strongest_saved_profiles()
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print("Could not scan saved Wi-Fi profiles: " + str(exc)[:200], flush=True)
            return False
    for profile in candidates:
        if profile["uuid"] == current_uuid: return True
        print("Trying saved Wi-Fi profile at signal " + str(profile["signal"]) + "%.", flush=True)
        result = run(["/usr/bin/nmcli", "--wait", "25", "connection", "up", "uuid", profile["uuid"], "ifname", IFACE], timeout=30, check=False)
        if result.returncode == 0 and active_uuid() == profile["uuid"]:
            print("Connected to the strongest available saved Wi-Fi profile.", flush=True)
            return True
        print("Saved Wi-Fi attempt failed; trying the next strongest profile.", flush=True)
    return False

def manager():
    ap = AP_ID
    # Allow normal saved-profile autoconnect to complete first.
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if active_wifi() and active_wifi() != ap: break
        time.sleep(5)
    prefer_strongest_saved_wifi()
    while True:
        if PENDING.exists():
            try:
                lines = PENDING.read_text().splitlines()
                if len(lines) > 1 and time.time() > int(lines[1]): PENDING.unlink(missing_ok=True)
                else: time.sleep(3); continue
            except (OSError, ValueError): PENDING.unlink(missing_ok=True)
        try:
            with LOCK.open("a") as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: time.sleep(2); continue
                active = active_wifi()
                if active and active != ap:
                    run(["/usr/bin/systemctl", "stop", "vipercoma-setup-net.service", "vipercoma-setup-portal.service"], timeout=15, check=False)
                elif active == ap:
                    run(["/usr/bin/systemctl", "start", "vipercoma-setup-net.service", "vipercoma-setup-portal.service"], timeout=20, check=False)
                else:
                    if not prefer_strongest_saved_wifi():
                        result = run(["/usr/bin/nmcli", "--wait", "25", "connection", "up", "uuid", ap_uuid(), "ifname", IFACE], timeout=30, check=False)
                        if result.returncode: print("Setup hotspot activation failed: " + (result.stderr or "network manager error").strip()[:240], flush=True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print("Wi-Fi manager retry: " + str(exc)[:200], flush=True)
        time.sleep(5)

def main():
    if os.geteuid() != 0: raise SystemExit("Requires root privileges.")
    os.umask(0o077)
    if sys.argv[1:] == ["manager"]: manager(); return
    if sys.argv[1:] == ["install-ap"]: install_ap(); return
    if len(sys.argv) == 3 and sys.argv[1] == "activate": activate(sys.argv[2]); return
    if sys.argv[1:] not in (["scan"], ["connect"]): raise SystemExit("Unsupported operation.")
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with LOCK.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if sys.argv[1] == "scan": result = {"networks": scan()}
            else:
                raw = sys.stdin.read(4097)
                if len(raw) > 4096: raise ValueError("Request is too large.")
                result = connect(json.loads(raw))
            fcntl.flock(lock, fcntl.LOCK_UN)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)[:240]}, ensure_ascii=False)); raise SystemExit(1)

if __name__ == "__main__": main()
