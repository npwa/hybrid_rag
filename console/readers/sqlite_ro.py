"""Read-only SQLite access to manifest.db (requirement C2): URI mode=ro plus PRAGMA query_only."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def is_read_only(conn: sqlite3.Connection) -> bool:
    """Probe: a write must fail. (Run against a read-only handle, so the probe cannot succeed.)"""
    try:
        conn.execute("CREATE TABLE _console_write_probe (x)")
    except sqlite3.OperationalError:
        return True
    conn.rollback()
    return False


def index_counts(conn: sqlite3.Connection) -> dict:
    files = dict(conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status").fetchall())
    chunks = dict(conn.execute("SELECT embedding_status, COUNT(*) FROM chunks GROUP BY embedding_status").fetchall())
    by_ext = [{"extension": r[0] or "", "count": r[1]} for r in conn.execute(
        "SELECT extension, COUNT(*) c FROM files GROUP BY extension ORDER BY c DESC, extension LIMIT 15")]
    return {
        "files_total": sum(files.values()), "files_by_status": files, "files_by_extension": by_ext,
        "chunks_total": sum(chunks.values()), "chunks_by_embedding_status": chunks,
    }
