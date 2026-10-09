"""Station local workspace; Wi-Fi changes use a narrowly scoped root helper."""
import argparse
import json
import hmac
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit
import ipaddress
import shutil
import socket
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, abort, send_file
from waitress import serve
from diagnostics import health as device_health, probe
from auth import STATE, session_key, password_matches, password_ready
from notes import NotesStore

VERSION = "2.1.0-wifi"
WIFI_HELPER = "/usr/local/libexec/vipercoma-wifi"
TOOLS = [
    {"id": "notes", "name": "Shared notes", "category": "files", "status": "Ready",
     "description": "Keep text and quick handoffs together on your Pi.",
     "note": "Local storage · up to 200 notes", "url": "/workspace#notes"},
    {"id": "diagnostics", "name": "Network diagnostics", "category": "network", "status": "Read only",
     "description": "Inspect addresses, routes, neighbor devices, DNS, and latency.",
     "note": "DNS and latency probes contact example.com and 1.1.1.1.", "url": "/workspace#diagnostics"},
    {"id": "health", "name": "Device health", "category": "network", "status": "Live readings",
     "description": "See memory, storage, uptime, temperature, and system details.",
     "note": "Readings come from this host.", "url": "/workspace#health"},
]


app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=8192, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Strict", PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
app.secret_key = session_key()
login_attempts = {}


@app.before_request
def local_access():
    # Reject unrecognized DNS names to reduce DNS-rebinding exposure.
    hostname = urlsplit(request.host_url).hostname or ""
    allowed_names = {"localhost", socket.gethostname(), socket.gethostname() + ".local", "pihole.local"}
    try:
        address = ipaddress.ip_address(hostname)
        allowed = (address.is_private or address.is_loopback
                   or address in ipaddress.ip_network("100.64.0.0/10"))
    except ValueError:
        allowed = hostname in allowed_names
    if not allowed:
        abort(400)
    if request.endpoint in (None, "static", "health", "login", "captive_check"):
        return
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify(error="Sign in to Station."), 401
        next_page = "/setup" if request.endpoint == "wifi_setup_page" else "/"
        return redirect(url_for("login", next=next_page))
    if request.method == "POST":
        validate_submission(request.headers.get("X-CSRF-Token"), session.get("csrf"))


def validate_submission(supplied, expected):
    # A session-bound token protects requests even when Origin is absent/null.
    origin = request.headers.get("Origin")
    if (origin not in (None, "null", request.host_url.rstrip("/"))
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
            or not supplied or not expected
            or not hmac.compare_digest(supplied.encode(), expected.encode())):
        abort(403)


@app.context_processor
def page_tokens():
    return {"csrf_token": session.get("csrf", "")}


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    next_page = request.args.get("next", "/")
    if next_page not in {"/", "/setup"}:
        next_page = "/"
    session.setdefault("login_csrf", secrets.token_urlsafe(24))
    if request.method == "POST":
        validate_submission(request.form.get("login_csrf"), session.get("login_csrf"))
        now = time.monotonic()
        key = request.remote_addr or ""
        history = [t for t in login_attempts.get(key, []) if now - t < 60]
        if len(history) >= 5:
            return render_template("login.html", error="Wait a minute before trying again.", next=next_page), 429
        if not password_ready():
            return render_template("login.html", error="Set your Station password on the device first.", next=next_page), 503
        if not password_matches(request.form.get("password", "")):
            history.append(now)
            if len(login_attempts) >= 256:
                login_attempts.clear()
            login_attempts[key] = history
            error = "That password did not match."
        else:
            login_attempts.pop(key, None)
            session.clear()
            session["authenticated"] = True
            session["csrf"] = secrets.token_urlsafe(24)
            session.permanent = True
            return redirect(next_page)
    return render_template("login.html", error=error, next=next_page)


@app.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


notes_store = NotesStore(STATE / "workspace")


@app.get("/workspace")
def workspace_page():
    return render_template("workspace.html", version=VERSION)


@app.get("/setup")
def wifi_setup_page():
    return render_template("wifi_setup.html")


@app.get("/api/wifi/networks")
def wifi_networks():
    return wifi_helper("scan")


@app.post("/api/wifi/connect")
def wifi_connect():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Choose a network and enter its password."), 400
    return wifi_helper("connect", data)


def wifi_helper(action, data=None):
    try:
        result = subprocess.run(
            ["sudo", "-n", WIFI_HELPER, action], input=json.dumps(data or {}),
            capture_output=True, text=True, timeout=30, check=False,
        )
        response = json.loads(result.stdout or "{}")
        if result.returncode:
            return jsonify(error=response.get("error", "Wi-Fi operation failed.")), 400
        return jsonify(response), 200 if action == "scan" else 202
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return jsonify(error="Wi-Fi setup helper is unavailable."), 503


@app.get("/generate_204")
@app.get("/hotspot-detect.html")
def captive_check():
    if not session.get("authenticated"):
        return redirect(url_for("login", next="/setup"))
    return redirect(url_for("wifi_setup_page"))


@app.get("/api/workspace/notes")
def notes_list():
    return jsonify(notes=notes_store.listing())


@app.post("/api/workspace/notes")
def notes_add():
    data = request.get_json(silent=True)
    try:
        notes_store.add(data.get("text") if isinstance(data, dict) else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True), 201


@app.post("/api/workspace/notes/<ident>/delete")
def notes_delete(ident):
    if not notes_store.delete(ident):
        abort(404)
    return jsonify(ok=True)


@app.get("/api/diagnostics/health")
def health_details():
    return jsonify(device_health())


@app.post("/api/diagnostics/<name>")
def diagnostics_run(name):
    try:
        return jsonify(probe(name))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


def device_status():
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0])
    disk = shutil.disk_usage(Path(__file__).resolve().parent)
    return {
        "version": VERSION,
        "hostname": socket.gethostname(),
        "memory_total_mib": memory["MemTotal"] / 1024,
        "memory_available_mib": memory["MemAvailable"] / 1024,
        "disk_free_gib": disk.free / 1024**3,
        "disk_total_gib": disk.total / 1024**3,
        "uptime_seconds": float(Path("/proc/uptime").read_text().split()[0]),
    }


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


@app.get("/")
def home():
    return render_template("index.html", version=VERSION, tools=TOOLS)


@app.get("/api/status")
def status():
    return jsonify(device_status())


@app.get("/healthz")
def health():
    return jsonify(status="ok", version=VERSION)


def tailscale_address():
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"], check=True, capture_output=True,
            text=True, timeout=5,
        )
        address = ipaddress.IPv4Address(result.stdout.strip())
        if address not in ipaddress.ip_network("100.64.0.0/10"):
            raise ValueError("Not a Tailscale address")
        return str(address)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit("Tailscale address unavailable. Reconnect Tailscale and try again.") from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Station local dashboard")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--local", action="store_true", help="Bind to loopback for Tailscale HTTPS Serve")
    parser.add_argument("--tailscale", action="store_true", help="Restrict access to the Tailscale IPv4 address")
    args = parser.parse_args()
    host = "127.0.0.1" if args.local else tailscale_address() if args.tailscale else "0.0.0.0"
    print(f"Station {VERSION}: listening on {host}:{args.port}", flush=True)
    print("Open http://pihole.local:8080/ on the same network.", flush=True)
    print("Use the Station password configured during setup.", flush=True)
    serve(app, host=host, port=args.port, threads=2)

