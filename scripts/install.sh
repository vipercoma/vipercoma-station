#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run: sudo bash scripts/install.sh' >&2; exit 1; fi
station_user=${SUDO_USER:-pi}
station_source=$(cd "$(dirname "$0")/.." && pwd)
station_state=/var/lib/vipercoma-workspace
station_unit=/etc/systemd/system/vipercoma-workspace.service
id "$station_user" >/dev/null
if [[ ! $station_user =~ ^[a-z_][a-z0-9_-]*$ || $station_source == *$'\n'* || $station_source == *'"'* ]]; then
  echo 'Unsupported installation user or path.' >&2; exit 1
fi
cd "$station_source"
if systemctl is-active --quiet vipercoma-wifi.service \
    && ! grep -Fqx 'HELPER_API = "vipercoma-wifi-helper-v1"' /usr/local/libexec/vipercoma-wifi-admin.py 2>/dev/null; then
  echo 'An unrecognized Wi-Fi manager is active. Inspect and preserve its configuration before upgrading it.' >&2; exit 1
fi
runuser -u "$station_user" -- python3 -m venv .venv
runuser -u "$station_user" -- .venv/bin/python -m pip install -r requirements.txt
runuser -u "$station_user" -- env STATION_STATE_DIR="$station_source/test-state" .venv/bin/python -W always::ResourceWarning -m unittest discover -s tests -v
install -d -m 700 -o "$station_user" -g "$(id -gn "$station_user")" "$station_state"
if [[ ! -f $station_state/password-hash ]]; then
  if [[ -f $station_state/access-code ]]; then
    runuser -u "$station_user" -- env STATION_STATE_DIR="$station_state" .venv/bin/python auth.py --migrate-password
  else
    runuser -u "$station_user" -- env STATION_STATE_DIR="$station_state" .venv/bin/python auth.py --set-password
  fi
fi
station_backup="$station_state/service-backup-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$station_backup"
station_was_active=false
if systemctl is-active --quiet vipercoma-workspace.service; then station_was_active=true; fi
station_was_enabled=false
if systemctl is-enabled --quiet vipercoma-workspace.service; then station_was_enabled=true; fi
if [[ -f $station_unit ]]; then cp -a "$station_unit" "$station_backup/previous.service"; fi
rollback() {
  trap - ERR
  set +e
  systemctl stop vipercoma-workspace.service
  if [[ -f $station_backup/previous.service ]]; then
    cp -a "$station_backup/previous.service" "$station_unit"
  else
    rm -f "$station_unit"
  fi
  systemctl daemon-reload
  if $station_was_active; then systemctl start vipercoma-workspace.service; fi
  if ! $station_was_enabled; then systemctl disable vipercoma-workspace.service; fi
  echo "Installation failed. Previous service configuration restored when available: $station_backup" >&2
  exit 1
}
trap rollback ERR
cat > "$station_unit" <<EOF
[Unit]
Description=vipercoma Station
After=network.target
[Service]
User=$station_user
WorkingDirectory="$station_source"
Environment=STATION_STATE_DIR=$station_state
ExecStart="$station_source/.venv/bin/python" "$station_source/app.py" --port 8080
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$station_state
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$station_unit"
systemctl daemon-reload
systemctl enable vipercoma-workspace.service
systemctl restart vipercoma-workspace.service
for attempt in {1..15}; do
  if .venv/bin/python scripts/check-health.py 2.2.0-wifi; then
    echo 'Station 2.2.0 Wi-Fi release is responding. Use your existing Station password.'
    echo 'Open http://pihole.local:8080 or the current LAN address.'
    echo "Previous service configuration: $station_backup"
    trap - ERR
    exit 0
  fi
  sleep 1
done
rollback
