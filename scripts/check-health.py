"""Quiet startup check for the exact expected release."""
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2) as response:
        data = json.load(response)
    raise SystemExit(0 if data == {'status':'ok', 'version':sys.argv[1]} else 1)
except (OSError, ValueError):
    raise SystemExit(1)
