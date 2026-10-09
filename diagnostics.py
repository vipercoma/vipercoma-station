"""Fixed read-only probes with time and output bounds."""
import platform
import shutil
import subprocess
from pathlib import Path

PROBES = {
    'addresses': ['ip', '-brief', 'address'],
    'routes': ['ip', 'route', 'show'],
    'ipv6': ['ip', '-6', 'route', 'show'],
    'neighbors': ['ip', 'neigh', 'show'],
    'dns': ['getent', 'ahostsv4', 'example.com'],
    'latency': ['ping', '-n', '-c', '3', '-W', '1', '1.1.1.1'],
}


def probe(name):
    command = PROBES.get(name)
    if command is None:
        raise ValueError('Choose a listed diagnostic.')
    if not shutil.which(command[0]):
        return {'ok': False, 'output': command[0] + ' is not installed.'}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=6)
        return {'ok': result.returncode == 0, 'output': (result.stdout + result.stderr)[:12000]}
    except (OSError, subprocess.SubprocessError):
        return {'ok': False, 'output': 'Diagnostic unavailable or timed out.'}


def health():
    data = {'system': platform.system(), 'architecture': platform.machine(), 'kernel': platform.release()}
    try:
        data['temperature_c'] = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
    except (OSError, ValueError):
        data['temperature_c'] = None
    try:
        data['load_average'] = Path('/proc/loadavg').read_text().split()[:3]
    except OSError:
        data['load_average'] = None
    return data
