"""Private session and password storage for Station."""
import argparse
import getpass
import os
import secrets
import tempfile
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

STATE = Path(os.environ['STATION_STATE_DIR']) if os.environ.get('STATION_STATE_DIR') else Path.home() / '.local/share/vipercoma-station'


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.station-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def session_key():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STATE / 'session-key'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    with os.fdopen(fd, 'w') as stream:
        key = secrets.token_urlsafe(32)
        stream.write(key + '\n')
    return key


def password_ready():
    return (STATE / 'password-hash').is_file()


def password_matches(value):
    try:
        hashed = (STATE / 'password-hash').read_text().strip()
    except OSError:
        return False
    return check_password_hash(hashed, value)


def set_password(value):
    if not isinstance(value, str) or len(value) < 8 or len(value) > 128:
        raise ValueError('Use a password of 8–128 characters.')
    atomic_text(STATE / 'password-hash', generate_password_hash(value, method='pbkdf2:sha256:600000') + '\n')
    # Rotate the session key so old browser sessions expire after restart.
    atomic_text(STATE / 'session-key', secrets.token_urlsafe(32) + '\n')


def migrate_password():
    if password_ready():
        return
    previous = STATE / 'access-code'
    if not previous.is_file():
        raise ValueError('No existing password. Run auth.py --set-password.')
    set_password(previous.read_text().strip())
    # Keep the private legacy file for recovery; it is never read by the web app.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Set the Station sign-in password privately.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--set-password', action='store_true')
    group.add_argument('--migrate-password', action='store_true')
    args = parser.parse_args()
    try:
        if args.migrate_password:
            migrate_password()
        else:
            password = getpass.getpass('Station password (you may use your Wi-Fi password): ')
            if password != getpass.getpass('Confirm password: '):
                raise ValueError('Passwords differ; nothing changed.')
            set_password(password)
        print('Station password configured. Restart Station if it is running.')
    except ValueError as exc:
        raise SystemExit(str(exc))
