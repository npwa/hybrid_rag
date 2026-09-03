"""SQLite manifest (manifest.db) — see step-1-requirements.md §5.

One row per source file, keyed by file_id (sha256 of the absolute path so the
identifier is stable even if the file's content later changes). Re-runs
upsert existing rows rather than duplicating them, and files that disappear
from the source tree are marked status='deleted' rather than removed, so
history/traceability is preserved.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_id             TEXT PRIMARY KEY,
    abs_path            TEXT NOT NULL,
    rel_path            TEXT NOT NULL,
    filename            TEXT NOT NULL,
    extension           TEXT,
    size_bytes          INTEGER,
    mtime               TEXT,
    content_hash        TEXT,
    category            TEXT NOT NULL,
    status              TEXT NOT NULL,
    extracted_text_path TEXT,
    ocr_used            INTEGER NOT NULL DEFAULT 0,
    ocr_confidence      REAL,
    sheet_names         TEXT,
    tags                TEXT,
    error_message       TEXT,
    last_processed      TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_rel_path ON files(rel_path);
"""

# Valid `status` values (documented here since SQLite has no enum type):
#   pending, extracted, ocr_extracted, ocr_low_confidence,
#   warning_empty_conversion, failed, encrypted, empty, skipped, deleted
STATUSES = {
    "pending",
    "extracted",
    "ocr_extracted",
    "ocr_low_confidence",
    "warning_empty_conversion",
    "failed",
    "encrypted",
    "empty",
    "skipped",
    "deleted",
}

CATEGORIES = {"include", "readme", "excluded", "unclassified"}


@dataclasses.dataclass
class FileRecord:
    file_id: str
    abs_path: str
    rel_path: str
    filename: str
    extension: Optional[str]
    size_bytes: int
    mtime: str
    content_hash: Optional[str]
    category: str
    status: str
    extracted_text_path: Optional[str] = None
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    sheet_names: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    error_message: Optional[str] = None
    last_processed: Optional[str] = None

    def as_row(self) -> dict:
        d = dataclasses.asdict(self)
        d["ocr_used"] = int(bool(d["ocr_used"]))
        d["sheet_names"] = json.dumps(d["sheet_names"]) if d["sheet_names"] is not None else None
        d["tags"] = json.dumps(d["tags"]) if d["tags"] is not None else None
        return d


class Manifest:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, file_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
        return cur.fetchone()

    def upsert(self, rec: FileRecord) -> None:
        row = rec.as_row()
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "file_id")
        sql = (
            f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(file_id) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, row)
        self.conn.commit()

    def mark_deleted(self, file_id: str, last_processed: str) -> None:
        self.conn.execute(
            "UPDATE files SET status = 'deleted', last_processed = ? WHERE file_id = ? AND status != 'deleted'",
            (last_processed, file_id),
        )
        self.conn.commit()

    def all_file_ids(self) -> set[str]:
        cur = self.conn.execute("SELECT file_id FROM files WHERE status != 'deleted'")
        return {r["file_id"] for r in cur.fetchall()}

    def status_counts(self) -> dict[str, int]:
        cur = self.conn.execute("SELECT status, COUNT(*) AS n FROM files GROUP BY status")
        return {r["status"]: r["n"] for r in cur.fetchall()}

    def category_counts(self) -> dict[str, int]:
        cur = self.conn.execute("SELECT category, COUNT(*) AS n FROM files GROUP BY category")
        return {r["category"]: r["n"] for r in cur.fetchall()}

    def extracted_text_claims(self) -> dict[str, dict[str, str]]:
        """{output_dir: {basename: file_id}} for every live (non-deleted) row that has
        written output — used to keep Markdown output filenames (§4b/§4d naming, which
        drops the original extension) collision-free and stable across re-runs."""
        cur = self.conn.execute(
            "SELECT file_id, extracted_text_path FROM files "
            "WHERE status != 'deleted' AND extracted_text_path IS NOT NULL"
        )
        claims: dict[str, dict[str, str]] = {}
        for row in cur.fetchall():
            p = PurePosixPath(row["extracted_text_path"])
            claims.setdefault(p.parent.as_posix(), {})[p.name] = row["file_id"]
        return claims

    def export_jsonl(self, out_path: Path) -> int:
        cur = self.conn.execute("SELECT * FROM files ORDER BY rel_path")
        n = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for row in cur:
                f.write(json.dumps(dict(row)) + "\n")
                n += 1
        return n


@contextlib.contextmanager
def open_manifest(db_path: Path) -> Iterator[Manifest]:
    m = Manifest(db_path)
    try:
        yield m
    finally:
        m.close()
