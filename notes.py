"""Bounded shared notes with explicit SQLite connection cleanup."""
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

LOCK = threading.Lock()


class NotesStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, text TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'workspace.sqlite', timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def listing(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM notes ORDER BY created DESC, id DESC LIMIT 200')]

    def add(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Write a note of 1–4000 characters.')
        with LOCK, self.connect() as db:
            if db.execute('SELECT COUNT(*) FROM notes').fetchone()[0] >= 200:
                raise ValueError('Keep up to 200 notes. Remove one first.')
            db.execute('INSERT INTO notes (id,text) VALUES (?,?)', (secrets.token_hex(16), text.strip()))

    def delete(self, ident):
        with self.connect() as db:
            return db.execute('DELETE FROM notes WHERE id=?', (ident,)).rowcount > 0
