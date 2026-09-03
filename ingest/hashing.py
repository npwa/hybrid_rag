"""sha256 helpers for file_id (path) and content_hash (bytes) — §5."""
from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def hash_path(abs_path: str) -> str:
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()


def hash_file_contents(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
