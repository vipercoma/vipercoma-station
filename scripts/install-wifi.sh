#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run: sudo bash scripts/install-wifi.sh' >&2; exit 1; fi

station_user=${SUDO_USER:-pi}
station_source=$(cd "$(dirname "$0")/.." && pwd)
helper=/usr/local/libexec/vipercoma-wifi-admin.py
portal=/usr/local/libexec/vipercoma-wifi-portal.py
wrapper=/usr/local/libexec/vipercoma-wifi
unit_dir=/etc/systemd/system
sudoers=/etc/sudoers.d/vipercoma-wifi
wrapper_tmp=$(mktemp)
sudoers_tmp=$(mktemp)
trap 'rm -f "$wrapper_tmp" "$sudoers_tmp"' EXIT

id "$station_user" >/dev/null
if [[ ! $station_user =~ ^[a-z_][a-z0-9_-]*$ || $station_source == *$'\n'* || $station_source == *'"'* ]]; then
  echo 'Unsupported user or project path.' >&2; exit 1
fi
systemctl is-active --quiet NetworkManager || { echo 'NetworkManager is not active.' >&2; exit 1; }
if [[ $(/usr/bin/nmcli -g GENERAL.TYPE device show wlan0 2>/dev/null || true) != wifi ]]; then
  echo 'NetworkManager does not expose wlan0 as a Wi-Fi device.' >&2; exit 1
fi
if [[ $(/usr/bin/nmcli -g WIFI-PROPERTIES.AP device show wlan0 2>/dev/null || true) != yes ]]; then
  echo 'wlan0 does not report access-point mode support.' >&2; exit 1
fi
command -v dnsmasq >/dev/null || { echo 'dnsmasq is required.' >&2; exit 1; }
command -v visudo >/dev/null || { echo 'visudo is required.' >&2; exit 1; }
command -v systemd-analyze >/dev/null || { echo 'systemd-analyze is required.' >&2; exit 1; }
for required in /usr/bin/nmcli /usr/bin/systemd-run /usr/sbin/runuser /usr/bin/python3 /usr/bin/systemctl /usr/bin/ss /usr/bin/curl; do
  [[ -x $required ]] || { echo "Missing required command: $required" >&2; exit 1; }
done
[[ -x /usr/sbin/dnsmasq ]] || { echo 'dnsmasq executable not found at /usr/sbin/dnsmasq.' >&2; exit 1; }
[[ -x $station_source/.venv/bin/python ]] || { echo 'Install Station first with sudo bash scripts/install.sh.' >&2; exit 1; }
[[ -f $unit_dir/vipercoma-workspace.service ]] || { echo 'Station service is not installed.' >&2; exit 1; }
if ! curl -fsS http://127.0.0.1:8080/healthz | grep -q '2.2.0-wifi'; then
  echo 'Upgrade and start Station 2.2.0-wifi before installing Wi-Fi setup.' >&2; exit 1
fi

# Refuse to overwrite a service/helper from another Wi-Fi implementation.
check_managed_file() {
  local source=$1 destination=$2
  if [[ -e $destination ]] && ! cmp -s "$source" "$destination"; then
    echo "Existing file differs from the Station Wi-Fi release: $destination" >&2
    echo 'Inspect and back it up before retrying; nothing has been installed.' >&2
    exit 1
  fi
}
install -d -m 755 /usr/local/libexec /etc/vipercoma-station
check_managed_file wifi_admin.py "$helper"
check_managed_file wifi_portal.py "$portal"
check_managed_file systemd/dnsmasq.conf /etc/vipercoma-station/dnsmasq.conf
check_managed_file systemd/vipercoma-wifi.service "$unit_dir/vipercoma-wifi.service"
check_managed_file systemd/vipercoma-setup-net.service "$unit_dir/vipercoma-setup-net.service"
check_managed_file systemd/vipercoma-setup-portal.service "$unit_dir/vipercoma-setup-portal.service"

cat > "$wrapper_tmp" <<'EOF'
#!/usr/bin/env bash
set -eu
if [[ $# -ne 1 || ( $1 != scan && $1 != connect ) ]]; then exit 2; fi
exec /usr/bin/python3 /usr/local/libexec/vipercoma-wifi-admin.py "$1"
EOF
if [[ -e $wrapper ]] && ! cmp -s "$wrapper_tmp" "$wrapper"; then
  echo "Existing helper wrapper differs: $wrapper. Inspect it before retrying." >&2; exit 1
fi
printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/vipercoma-wifi scan, /usr/local/libexec/vipercoma-wifi connect\n' "$station_user" > "$sudoers_tmp"
chmod 440 "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
if [[ -e $sudoers ]] && ! cmp -s "$sudoers_tmp" "$sudoers"; then
  echo "Existing sudo policy differs: $sudoers. Inspect it before retrying." >&2; exit 1
fi

cd "$station_source"
.venv/bin/python -m unittest discover -s tests -v
if ! systemctl is-active --quiet vipercoma-setup-net.service && ss -H -lntu '( sport = :53 )' | grep -q .; then
  echo 'Port 53 already has a listener. Resolve the DNS service conflict before enabling captive setup.' >&2
  exit 1
fi

# Create or validate the isolated AP profile only after all static checks pass.
/usr/bin/python3 - "$station_source/wifi_admin.py" <<'PYCONFIG'
import runpy, sys
runpy.run_path(sys.argv[1], run_name="__station_install__")["install_ap"]()
PYCONFIG

install -m 755 wifi_admin.py "$helper"
install -m 755 wifi_portal.py "$portal"
install -m 644 systemd/dnsmasq.conf /etc/vipercoma-station/dnsmasq.conf
install -m 644 systemd/vipercoma-wifi.service "$unit_dir/"
install -m 644 systemd/vipercoma-setup-net.service "$unit_dir/"
install -m 644 systemd/vipercoma-setup-portal.service "$unit_dir/"
install -m 755 "$wrapper_tmp" "$wrapper"
install -o root -g root -m 440 "$sudoers_tmp" "$sudoers"
systemd-analyze verify \
  "$unit_dir/vipercoma-workspace.service" \
  "$unit_dir/vipercoma-wifi.service" \
  "$unit_dir/vipercoma-setup-net.service" \
  "$unit_dir/vipercoma-setup-portal.service"
systemctl daemon-reload
systemctl enable vipercoma-wifi.service
systemctl restart vipercoma-wifi.service
for attempt in {1..25}; do
  if curl -fsS http://127.0.0.1:8080/healthz | grep -q '2.2.0-wifi'; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8080/healthz | grep -q '2.2.0-wifi' || {
  echo 'Station is not responding as version 2.2.0-wifi.' >&2; exit 1;
}
echo 'Saved Wi-Fi is tried first; the setup hotspot starts when it is unavailable.'
echo 'Connect to vipercoma-setup and open http://10.77.0.1:8080/setup.'
echo 'After setup, join the same Wi-Fi on your phone and open http://pihole.local:8080.'
echo 'Station sign-in remains separate from both Wi-Fi passwords.'
