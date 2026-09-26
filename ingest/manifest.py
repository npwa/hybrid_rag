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
import hashlib
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

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id             TEXT PRIMARY KEY,
    file_id              TEXT NOT NULL,
    chunk_index          INTEGER NOT NULL,
    text                 TEXT NOT NULL,
    char_start           INTEGER,
    char_end             INTEGER,
    source_content_hash  TEXT,
    rel_path             TEXT,
    category             TEXT,
    extension            TEXT,
    tags                 TEXT,
    sheet_name           TEXT,
    ocr_used             INTEGER NOT NULL DEFAULT 0,
    ocr_confidence       REAL,
    embedding_status     TEXT NOT NULL DEFAULT 'pending',
    created_at           TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_status ON chunks(embedding_status);
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


@dataclasses.dataclass
class ChunkRecord:
    chunk_id: str
    file_id: str
    chunk_index: int
    text: str
    char_start: Optional[int]
    char_end: Optional[int]
    source_content_hash: Optional[str]
    rel_path: Optional[str] = None
    category: Optional[str] = None
    extension: Optional[str] = None
    tags: Optional[list[str]] = None
    sheet_name: Optional[str] = None
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    embedding_status: str = "pending"
    created_at: Optional[str] = None

    def as_row(self) -> dict:
        d = dataclasses.asdict(self)
        d["ocr_used"] = int(bool(d["ocr_used"]))
        d["tags"] = json.dumps(d["tags"]) if d["tags"] is not None else None
        return d


class Manifest:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        # WAL lets worker processes hold their own read-only connection concurrently
        # with this single writer (§ concurrency model in pipeline.py); NORMAL sync
        # trades a small durability window for much fewer fsyncs on bulk writes —
        # an acceptable tradeoff for a personal ingestion tool, not a transactional DB.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, file_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
        return cur.fetchone()

    def upsert(self, rec: FileRecord) -> None:
        """Does not commit — batch several upserts and call commit() periodically
        (see pipeline.run()). Committing every single row is the dominant SQLite
        bottleneck at large file counts (one fsync per row); batching is what makes
        this scale to hundreds of thousands of files without the DB becoming the
        slow part of the run."""
        row = rec.as_row()
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "file_id")
        sql = (
            f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(file_id) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, row)

    def mark_deleted(self, file_id: str, last_processed: str) -> None:
        """Does not commit — see upsert()."""
        self.conn.execute(
            "UPDATE files SET status = 'deleted', last_processed = ? WHERE file_id = ? AND status != 'deleted'",
            (last_processed, file_id),
        )

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

    # --- chunks (Step 3) --------------------------------------------------

    def chunkable_files(self) -> list[sqlite3.Row]:
        """Files with real extracted text — the only rows Step 3 considers."""
        cur = self.conn.execute(
            "SELECT file_id, rel_path, filename, extension, category, content_hash, "
            "extracted_text_path, ocr_used, ocr_confidence, sheet_names, tags "
            "FROM files WHERE status IN ('extracted', 'ocr_extracted', 'ocr_low_confidence')"
        )
        return cur.fetchall()

    def deleted_file_ids(self) -> set[str]:
        cur = self.conn.execute("SELECT file_id FROM files WHERE status = 'deleted'")
        return {r["file_id"] for r in cur.fetchall()}

    def insert_chunk(self, rec: ChunkRecord) -> None:
        """Does not commit — see upsert(). Chunk rows are never updated in place — a
        changed file's old chunks are soft-deleted (mark_chunks_deleted_for_file, same
        as a removed source file — Step 4 needs the embedding_status='deleted' signal to
        clean up anything already embedded/indexed under the old chunk_ids) and new ones
        inserted, so this is always a plain INSERT, never an UPDATE.

        chunk_ids are versioned by the source file's content hash (chunking/pipeline.py),
        so a modified file's new chunks never collide with its own soft-deleted ones. One
        collision is still possible: a file that reverts to *identical* earlier content
        (deleted then restored, or edited then undone) before Step 4 has purged the
        old rows would derive the same ids. Rather than fail, that chunk gets a salted id —
        the old row stays put under its own id and is cleaned up from the vector/FTS5
        stores as normal, and the new row is embedded fresh, so no duplicate ever reaches
        either store."""
        for attempt in range(1000):
            row = rec.as_row()
            if attempt:
                row["chunk_id"] = hashlib.sha256(f"{rec.chunk_id}:{attempt}".encode("utf-8")).hexdigest()
            cols = list(row.keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            try:
                self.conn.execute(f"INSERT INTO chunks ({', '.join(cols)}) VALUES ({placeholders})", row)
                return
            except sqlite3.IntegrityError as e:
                if "chunks.chunk_id" not in str(e):
                    raise
        raise RuntimeError(f"could not find a free chunk_id for {rec.chunk_id}")

    def mark_chunks_deleted_for_file(self, file_id: str) -> int:
        """Does not commit — see upsert(). Returns rows affected."""
        cur = self.conn.execute(
            "UPDATE chunks SET embedding_status = 'deleted' WHERE file_id = ? AND embedding_status != 'deleted'",
            (file_id,),
        )
        return cur.rowcount

    def chunk_counts(self) -> dict[str, int]:
        cur = self.conn.execute("SELECT embedding_status, COUNT(*) AS n FROM chunks GROUP BY embedding_status")
        return {r["embedding_status"]: r["n"] for r in cur.fetchall()}

    def chunks_by_status(self, status: str, limit: int, after_chunk_id: str = "") -> list[sqlite3.Row]:
        """Keyset-paginated (not OFFSET) so this stays a bounded, indexed read
        regardless of how large the `chunks` table gets (§8 of step-3-requirements.md)."""
        cur = self.conn.execute(
            "SELECT * FROM chunks WHERE embedding_status = ? AND chunk_id > ? ORDER BY chunk_id LIMIT ?",
            (status, after_chunk_id, limit),
        )
        return cur.fetchall()

    def mark_chunks_embedded(self, chunk_ids: list[str]) -> None:
        """Does not commit — see upsert()."""
        self.conn.executemany(
            "UPDATE chunks SET embedding_status = 'embedded' WHERE chunk_id = ?",
            [(c,) for c in chunk_ids],
        )

    def purge_chunks(self, chunk_ids: list[str]) -> None:
        """Does not commit — see upsert(). For `deleted` chunks Step 4 has already
        removed from the vector/FTS5 stores — their job (signal "please clean this up")
        is done, so the row itself is no longer needed. History for a removed file is
        already preserved at the `files` table level (status='deleted' there); a chunk_id
        has no independent meaning once decoupled from a live file."""
        self.conn.executemany("DELETE FROM chunks WHERE chunk_id = ?", [(c,) for c in chunk_ids])

    # --- FTS5 (Step 4 sparse leg) -------------------------------------------------

    def ensure_fts5(self, table: str) -> None:
        self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING "
            "fts5(chunk_id UNINDEXED, text, rel_path UNINDEXED, tags UNINDEXED)"
        )
        self.conn.commit()

    def fts5_insert_batch(self, table: str, rows: list[dict]) -> None:
        """Does not commit — see upsert()."""
        self.conn.executemany(
            f"INSERT INTO {table} (chunk_id, text, rel_path, tags) VALUES (:chunk_id, :text, :rel_path, :tags)",
            rows,
        )

    def fts5_delete_chunk_ids(self, table: str, chunk_ids: list[str]) -> None:
        """Does not commit — see upsert()."""
        self.conn.executemany(f"DELETE FROM {table} WHERE chunk_id = ?", [(c,) for c in chunk_ids])


@contextlib.contextmanager
def open_manifest(db_path: Path) -> Iterator[Manifest]:
    m = Manifest(db_path)
    try:
        yield m
    finally:
        m.close()
