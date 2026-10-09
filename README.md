# vipercoma Station

[![Station interaction preview](docs/previews/station-interaction-preview.jpg)](docs/previews/station-interaction-preview.mp4)

**[Watch the short interface preview](docs/previews/station-interaction-preview.mp4)** · Mouse glow, click reactions, tabs and menus. This is an offline design preview.

A lightweight, local workspace for a dedicated Raspberry Pi or Linux computer.
Version **2.0.0**. Native Python services; no containers or extra hardware.

## Tools

| Tool | What it does |
| --- | --- |
| Shared notes | Persist up to 200 notes, each up to 4000 characters |
| Network diagnostics | Read addresses, IPv4/IPv6 routes and neighbor cache; run fixed DNS and latency checks |
| Device health | Show RAM availability, storage, uptime, CPU temperature and load |

The interface uses neutral dark/light themes, rounded controls and a dotted background. Tool pages include mouse glow, click feedback, theme switching, optional mouse effects and sign-out. Reduced-motion preferences are respected. No traffic blocking, Wi-Fi switching, gateway experiments, scheduler or file-transfer tool is included.

## Install

Target: Linux with systemd, Python 3.12 or 3.13, and python3-venv. Optional diagnostic commands: ip, getent and ping. Missing commands report unavailable.

From a fresh user-owned checkout or extracted release:

```bash
sudo bash scripts/install.sh
```

The installer tests the application before changing its service. It creates or updates `vipercoma-workspace.service`, preserves the previous unit and checks the exact release health. It does not modify Wi-Fi, SSH, firewall or Tailscale settings.

Open **http://pihole.local:8080** or the host's current LAN address. Another Linux host uses its own hostname. Sign in with the password chosen during setup.

For an existing workspace, the stored sign-in password is migrated to a hash, retaining the same password and existing notes. The private legacy credential file is retained for recovery and is not read by the new web app. You may choose the same password as your Wi-Fi; this is a separate stored sign-in password, not automatic synchronization with network settings.

## Change the password

Run as the service user from the project directory:

```bash
STATION_STATE_DIR=/var/lib/vipercoma-workspace .venv/bin/python auth.py --set-password
sudo systemctl restart vipercoma-workspace.service
```

Input is hidden. The password is hashed; changing it rotates the session key. Keep runtime files private.

## Local development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
STATION_STATE_DIR="$PWD/preview-state" .venv/bin/python auth.py --set-password
STATION_STATE_DIR="$PWD/preview-state" .venv/bin/python app.py --local --port 8082
```

## Validation and updates

```bash
.venv/bin/python -W always::ResourceWarning -m unittest discover -s tests -v
bash scripts/update.sh
```

CI checks supported Python versions, JavaScript and shell syntax, notes persistence/limits, sign-in, request boundaries and bounded diagnostics. Successful tests do not establish physical Pi performance or radio behavior.

The earlier 1.0.1 workspace ran on the user's Pi with 199 MiB RAM available out of 416 MiB reported total at one idle reading. Version 2.0.0 memory usage and installation are not yet physically verified. Measure OS plus application use before claiming the 500 MB target is met.

Diagnostics use fixed commands, a six-second timeout and bounded displayed output. DNS looks up example.com; latency sends three ICMP probes to 1.1.1.1. Neighbor cache is partial and may contain stale entries. No probe proves full internet availability.

## Private runtime data

Production data lives in `/var/lib/vipercoma-workspace`, outside the source checkout. Notes retain the existing `workspace/workspace.sqlite` path for migration. Old uploads remain private on disk but have no download or transfer endpoints in this release.

Do not publish runtime directories, Wi-Fi profiles, passwords, session keys, database files or recovery archives. The web app uses local HTTP with authenticated sessions and CSRF checks; keep it on a trusted private network. Do not expose port 8080 publicly.

To stop Station:

```bash
sudo systemctl disable --now vipercoma-workspace.service
```

Keep previous source checkouts and recovery archives until the new release is validated.
