"""Private, file-backed Markdown library with a read-only AI API token."""
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from auth import STATE, atomic_text

MAX_FILES = 500
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".py", ".sh", ".ps1",
                 ".js", ".ts", ".toml", ".yaml", ".yml", ".ini", ".cfg",
                 ".html", ".css"}
TOKEN_HASH = STATE / "memory-read-token"


class MemoryVault:
    def __init__(self, root=None):
        self.root = Path(root or STATE / "memory")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, filename):
        if not isinstance(filename, str) or not filename or len(filename) > 120:
            raise ValueError("Choose a valid Markdown filename.")
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ValueError("Folders and path separators are not allowed in filenames.")
        if filename.startswith(".") or Path(filename).suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("Choose a supported Markdown, text, JSON, or source-code file.")
        if any(ord(char) < 32 for char in filename):
            raise ValueError("The filename contains unsupported characters.")
        path = self.root / filename
        if path.is_symlink() or path.parent.resolve() != self.root.resolve():
            raise ValueError("That file path is not allowed.")
        return path

    def listing(self):
        files = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            stat = path.stat()
            files.append({"name": path.name, "bytes": stat.st_size, "updated": int(stat.st_mtime)})
        return files[:MAX_FILES]

    def read(self, filename):
        path = self._path(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("This file exceeds the read limit.")
        return path.read_text(encoding="utf-8")

    def save(self, filename, content, replace=False):
        path = self._path(filename)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Add some Markdown content first.")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Each Markdown file must be 512 KiB or smaller.")
        if path.exists() and not replace:
            raise FileExistsError(filename)
        current_total = sum(item.stat().st_size for item in self.root.iterdir()
                            if item.is_file() and item.suffix.lower() in TEXT_SUFFIXES)
        old_size = path.stat().st_size if path.exists() else 0
        if not path.exists() and len(self.listing()) >= MAX_FILES:
            raise ValueError("The library is full. Remove a file first.")
        if current_total - old_size + len(content.encode("utf-8")) > MAX_TOTAL_BYTES:
            raise ValueError("The library is limited to 20 MiB total.")
        temporary = self.root / ("." + secrets.token_hex(12) + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def search(self, query, limit=30):
        if not isinstance(query, str) or not query.strip() or len(query) > 160:
            raise ValueError("Enter a search phrase of 1–160 characters.")
        terms = query.casefold().split()
        results = []
        for item in self.listing():
            try:
                content = self.read(item["name"])
            except (OSError, ValueError, UnicodeError):
                continue
            haystack = (item["name"] + "\n" + content).casefold()
            if all(term in haystack for term in terms):
                results.append({**item, "excerpt": content[:240]})
                if len(results) >= limit:
                    break
        return results

    def delete(self, filename):
        path = self._path(filename)
        if not path.is_file():
            return False
        path.unlink()
        return True


def issue_read_token():
    token = "vcm_" + secrets.token_urlsafe(32)
    # A random 256-bit bearer token already has high entropy; a fast digest
    # avoids imposing password-hash cost on every read request from the Pi.
    atomic_text(TOKEN_HASH, hashlib.sha256(token.encode("ascii")).hexdigest() + "\n")
    return token


def read_token_matches(value):
    if not isinstance(value, str) or len(value) > 160:
        return False
    try:
        saved = TOKEN_HASH.read_text(encoding="utf-8").strip()
        supplied = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return hmac.compare_digest(saved, supplied)
    except (OSError, ValueError):
        return False


def revoke_read_token():
    TOKEN_HASH.unlink(missing_ok=True)
