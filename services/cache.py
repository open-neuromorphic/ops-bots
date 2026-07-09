import os
import time
import hashlib
from pathlib import Path
import config

def _ensure_dir(subdir: str) -> Path:
    p = Path(config.CACHE_DIR) / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p

def get(key: str, subdir: str = "bundles") -> Path | None:
    """Returns path if cache entry exists, else None."""
    p = _ensure_dir(subdir) / key
    return p if p.exists() else None

def put(key: str, content: str | bytes, subdir: str = "bundles") -> Path:
    """Writes content to cache, returns path."""
    p = _ensure_dir(subdir) / key
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if isinstance(content, bytes) else "utf-8"
    with open(p, mode, encoding=encoding) as f:
        f.write(content)
    return p

def invalidate(key: str, subdir: str = "bundles") -> None:
    """Removes an entry from the cache."""
    p = _ensure_dir(subdir) / key
    if p.exists():
        p.unlink()

def list_keys(subdir: str = "bundles") -> list[str]:
    """Returns a list of filename keys in the specified cache subdirectory."""
    p = _ensure_dir(subdir)
    return [f.name for f in p.glob("*") if f.is_file()]

def hash_of(path: Path) -> str:
    """Returns SHA-256 hex digest of file content."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def is_stale(entry, source_path: Path) -> bool:
    """True if source file has changed since it was cached/summarized."""
    if not getattr(entry, "content_hash", None):
        return True
    return entry.content_hash != hash_of(source_path)

def is_expired(path: Path, max_age_seconds: int) -> bool:
    """True if the file's age exceeds max_age_seconds."""
    if not path.exists():
        return True
    return (time.time() - os.path.getmtime(path)) > max_age_seconds