"""Per-run orchestration: read files -> split -> chunks table.

Concurrency model — identical in shape to ingest/pipeline.py's, by design
(step-3-requirements.md §8 explicitly calls for reusing it): splitting a
file's text is CPU-bound and embarrassingly parallel across files, so it
runs in a process pool. Workers are pure and stateless — each opens its own
read-only connection to manifest.db to check whether a file's chunks are
already up to date, does the splitting if not, and returns fully-formed
chunk rows. The main process is the sole writer: it deletes a changed file's
stale chunks, inserts the new ones, and batches commits.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from chunking.config import ChunkConfig
from chunking.splitters import split_text
from ingest.manifest import ChunkRecord, Manifest

log = logging.getLogger("chunk")

_COMMIT_BATCH = 200


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _chunk_id(file_id: str, index: int) -> str:
    return hashlib.sha256(f"{file_id}:{index}".encode("utf-8")).hexdigest()


@dataclass
class ChunkWorkResult:
    file_id: str
    rel_path: str
    status: str  # unchanged | chunked | empty_text | read_error | failed
    chunk_rows: list[ChunkRecord] = field(default_factory=list)
    error_message: str | None = None


# --- Worker process state & entry point -------------------------------------------
_worker_config: ChunkConfig | None = None
_worker_conn: sqlite3.Connection | None = None


def _init_worker(config: ChunkConfig, manifest_db_path: str) -> None:
    global _worker_config, _worker_conn
    _worker_config = config
    _worker_conn = sqlite3.connect(f"file:{manifest_db_path}?mode=ro", uri=True)
    _worker_conn.row_factory = sqlite3.Row


def _existing_source_hashes(file_id: str) -> set[str | None]:
    cur = _worker_conn.execute(
        "SELECT DISTINCT source_content_hash FROM chunks WHERE file_id = ? AND embedding_status != 'deleted'",
        (file_id,),
    )
    return {r["source_content_hash"] for r in cur.fetchall()}


def _worker_task(file_row: dict) -> ChunkWorkResult:
    config = _worker_config
    file_id = file_row["file_id"]
    rel_path = file_row["rel_path"]
    content_hash = file_row["content_hash"]

    existing_hashes = _existing_source_hashes(file_id)
    if existing_hashes == {content_hash}:
        return ChunkWorkResult(file_id, rel_path, "unchanged")

    text_path = config.extracted_text_dir / file_row["extracted_text_path"]
    try:
        text = text_path.read_text(encoding="utf-8")
    except OSError as e:
        return ChunkWorkResult(file_id, rel_path, "read_error", error_message=str(e))

    if not text.strip():
        return ChunkWorkResult(file_id, rel_path, "empty_text")

    try:
        spans = split_text(
            text,
            extension=file_row["extension"] or "",
            category=file_row["category"] or "",
            target=config.chunk_target_chars,
            overlap=config.chunk_overlap_chars,
            min_section=config.min_section_chars,
        )
    except Exception as e:
        # One bad file must never abort the run — same invariant as Step 1 (§6).
        return ChunkWorkResult(file_id, rel_path, "failed", error_message=f"unhandled exception: {e}")

    now = _now()
    rows = []
    for i, span in enumerate(spans):
        rec = ChunkRecord(
            chunk_id=_chunk_id(file_id, i),
            file_id=file_id,
            chunk_index=i,
            text=span.text,
            char_start=span.start,
            char_end=span.end,
            source_content_hash=content_hash,
            rel_path=rel_path,
            category=file_row["category"],
            extension=file_row["extension"],
            tags=file_row["tags"],
            sheet_name=span.sheet_name,
            ocr_used=bool(file_row["ocr_used"]),
            ocr_confidence=file_row["ocr_confidence"],
            embedding_status="pending",
            created_at=now,
        )
        rows.append(rec)

    return ChunkWorkResult(file_id, rel_path, "chunked", chunk_rows=rows)


# --- Main-process side --------------------------------------------------------------

def run(config: ChunkConfig, manifest: Manifest, limit: int | None = None) -> dict:
    import json as _json

    files = manifest.chunkable_files()
    if limit is not None:
        files = files[:limit]

    counts = {"unchanged": 0, "chunked": 0, "empty_text": 0, "read_error": 0, "failed": 0}
    chunks_created = 0
    since_commit = 0

    def to_row_dict(r) -> dict:
        d = dict(r)
        d["tags"] = _json.loads(d["tags"]) if d.get("tags") else None
        return d

    with ProcessPoolExecutor(
        max_workers=config.max_workers,
        initializer=_init_worker,
        initargs=(config, str(config.manifest_db)),
    ) as executor:
        pending: set = set()
        idx = 0

        def submit_next() -> bool:
            nonlocal idx
            if idx >= len(files):
                return False
            pending.add(executor.submit(_worker_task, to_row_dict(files[idx])))
            idx += 1
            return True

        for _ in range(config.max_workers * 4):
            if not submit_next():
                break

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                wr: ChunkWorkResult = fut.result()
                counts[wr.status] = counts.get(wr.status, 0) + 1

                if wr.status == "chunked":
                    manifest.delete_chunks_for_file(wr.file_id)
                    for rec in wr.chunk_rows:
                        manifest.insert_chunk(rec)
                    chunks_created += len(wr.chunk_rows)
                    log.info("CHUNKED %s (%d chunks)", wr.rel_path, len(wr.chunk_rows))
                elif wr.status == "unchanged":
                    log.debug("UNCHANGED %s", wr.rel_path)
                elif wr.status == "empty_text":
                    log.warning("EMPTY_TEXT %s: extracted text file is blank", wr.rel_path)
                else:
                    log.warning("%s %s: %s", wr.status.upper(), wr.rel_path, wr.error_message)

                since_commit += 1
                if since_commit >= _COMMIT_BATCH:
                    manifest.commit()
                    since_commit = 0
                submit_next()

    manifest.commit()

    stale_deleted = 0
    if limit is None:
        for file_id in manifest.deleted_file_ids():
            stale_deleted += manifest.mark_chunks_deleted_for_file(file_id)
        manifest.commit()
        if stale_deleted:
            log.info("MARKED_DELETED %d chunk(s) for source files no longer present", stale_deleted)

    return {
        "files_considered": len(files),
        "chunks_created": chunks_created,
        "chunks_marked_deleted": stale_deleted,
        **counts,
    }
