"""Per-run orchestration: walk -> classify -> hash -> extract -> manifest.

Idempotency (§8): every file's content_hash is recomputed each run and
compared against the stored value (not mtime, which can change without the
content changing). Unchanged files are a no-op; only new or changed files
are (re-)extracted. Files no longer present on disk are marked `deleted`
rather than removed from the manifest, preserving history (§5).

Concurrency model (added for scale — see step-1-requirements.md §9a):
extraction (OCR / PDF parsing / LibreOffice conversion) is CPU-bound and the
dominant cost per file, so it runs in a process pool — one worker process per
file in flight, up to `config.max_workers`. Workers are pure and stateless:
each opens its own *read-only* connection to manifest.db (safe to share with
the single writer under WAL mode) to look up a file's prior state, does all
the expensive work, and returns a result — it never writes to the database,
the filesystem, or the log. The main process is the sole writer: it consumes
worker results as they complete, does the (order-dependent) Markdown output
naming, writes extracted text, batches manifest upserts, and logs every
outcome. This keeps the single-writer SQLite invariant intact while using
all available cores for the part of the work that actually needs them.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ingest.classify import classify, extension_of
from ingest.config import Config
from ingest.extractors import extract
from ingest.hashing import hash_file_contents, hash_path
from ingest.manifest import FileRecord, Manifest
from ingest.walker import walk

log = logging.getLogger("ingest")

# Statuses that indicate we have usable extracted text worth writing to disk.
_TEXT_STATUSES = {"extracted", "ocr_extracted", "ocr_low_confidence"}

# How many manifest upserts to batch per SQLite commit (§ concurrency model above) —
# committing every single row is the dominant bottleneck at large file counts (one
# fsync per row); batching is what makes this scale to hundreds of thousands of files.
_COMMIT_BATCH = 200


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_markdown_output(category: str, ext: str) -> bool:
    """README/TODO conversions and plain whitelisted .md files all produce genuine
    Markdown, not incidental plain text — so they get a clean `.md` output name
    instead of the txt/text/pdf/... path's `<original-filename>.txt`."""
    return category == "readme" or ext == "md"


def _assign_markdown_name(registry: dict, dir_key: str, stem: str, file_id: str) -> str:
    """Pick `<stem>.md`, or `<stem>-2.md`, `<stem>-3.md`, ... on a collision with a
    *different* file (§4b/§4d) — e.g. a directory containing both `README` and
    `README.txt`, which would otherwise both want the same output name once the
    original extension is dropped."""
    claimed = registry.setdefault(dir_key, {})
    n = 1
    name = f"{stem}.md"
    while name in claimed and claimed[name] != file_id:
        n += 1
        name = f"{stem}-{n}.md"
    claimed[name] = file_id
    return name


def _write_extracted_text(
    config: Config, rel_path: str, filename: str, text: str,
    *, category: str, ext: str, file_id: str, prior_path: str | None, registry: dict,
) -> str:
    rel_dir = Path(rel_path).parent
    dir_key = rel_dir.as_posix()

    if _is_markdown_output(category, ext):
        if prior_path is not None and PurePosixPath(prior_path).parent.as_posix() == dir_key:
            # Stable across re-runs: a file that already owns a slot (canonical or
            # suffixed) keeps it rather than being renumbered on every re-extraction.
            out_name = PurePosixPath(prior_path).name
            registry.setdefault(dir_key, {})[out_name] = file_id
        else:
            stem = Path(filename).stem
            out_name = _assign_markdown_name(registry, dir_key, stem, file_id)
    else:
        out_name = f"{filename}.txt"

    out_dir = config.extracted_text_dir / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name
    out_path.write_text(text, encoding="utf-8")
    return out_path.relative_to(config.extracted_text_dir).as_posix()


def _base_record(file_id, abs_path, rel_path, filename, ext, size, mtime, category, status, **kw) -> FileRecord:
    return FileRecord(
        file_id=file_id,
        abs_path=str(abs_path),
        rel_path=rel_path,
        filename=filename,
        extension=ext,
        size_bytes=size,
        mtime=mtime,
        content_hash=kw.pop("content_hash", None),
        category=category,
        status=status,
        last_processed=_now(),
        **kw,
    )


@dataclass
class WorkResult:
    """Everything a worker process learned about one file — picklable, and carries
    no filesystem/DB side effects. `kind` tells _finalize() (main process) exactly
    which of process_file's old branches this came from, so logging stays identical
    to the pre-parallel implementation."""
    kind: str  # permission_error | empty | excluded | unclassified | read_error | unchanged | result
    file_id: str
    abs_path: str
    rel_path: str
    filename: str
    ext: str
    size: int
    mtime: str
    category: str
    status: str
    content_hash: str | None = None
    text: str | None = None
    reused: bool = False
    prior_extracted_text_path: str | None = None
    ocr_used: bool = False
    ocr_confidence: float | None = None
    sheet_names: list[str] | None = None
    tags: list[str] | None = None
    error_message: str | None = None


# --- Worker process state & entry point -------------------------------------------
# Populated once per worker process by _init_worker (ProcessPoolExecutor initializer),
# not per task — cheap even with a large manifest.db, since it's just opening a
# connection, not loading data.
_worker_config: Config | None = None
_worker_conn: sqlite3.Connection | None = None


def _init_worker(config: Config, manifest_db_path: str) -> None:
    global _worker_config, _worker_conn

    # Force every numeric/OCR library to single-threaded mode inside this worker.
    # Tesseract (via OpenMP), and potentially other C libraries in the extraction
    # path, spawn their own internal thread pool sized to the CPU count by default.
    # With N worker *processes* already providing the parallelism across files, each
    # one also fanning out to N internal threads causes N² oversubscription — e.g. 16
    # worker processes x 16 OpenMP threads each = 256-way contention on a 16-core
    # box. That's not a hypothetical: an early benchmark of this pool (16 workers,
    # no thread cap) took 75 minutes wall-clock on the real corpus, ~3.4x *slower*
    # than the original single-threaded 22-minute run, despite ~14.7x average core
    # utilization (1109 CPU-minutes of work done in 75 minutes) — busy, but almost
    # all of it wasted on contention rather than useful work. Pinning every library
    # to one thread per worker process is the fix: parallelism comes entirely from
    # the process pool, not from threads within it.
    for var in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[var] = "1"

    _worker_config = config
    # Read-only: workers never write. Safe to share with the main process's writer
    # connection because Manifest opens the DB in WAL mode (concurrent readers + one
    # writer).
    _worker_conn = sqlite3.connect(f"file:{manifest_db_path}?mode=ro", uri=True)
    _worker_conn.row_factory = sqlite3.Row


def _lookup_existing(file_id: str) -> sqlite3.Row | None:
    cur = _worker_conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
    return cur.fetchone()


def _worker_task(abs_path_str: str, rel_path: str) -> WorkResult:
    config = _worker_config
    abs_path = Path(abs_path_str)
    filename = abs_path.name
    ext = extension_of(filename)
    file_id = hash_path(abs_path_str)
    category = classify(filename, config)

    try:
        st = abs_path.stat()
    except OSError as e:
        return WorkResult("permission_error", file_id, abs_path_str, rel_path, filename, ext,
                           0, "", category, "failed", error_message=str(e))

    size = st.st_size
    mtime = datetime.fromtimestamp(st.st_mtime).isoformat()

    if size == 0:
        return WorkResult("empty", file_id, abs_path_str, rel_path, filename, ext,
                           size, mtime, category, "empty")

    if category in ("excluded", "unclassified"):
        return WorkResult(category, file_id, abs_path_str, rel_path, filename, ext,
                           size, mtime, category, "skipped")

    # category is "include" or "readme" from here on — compute content hash for change detection.
    try:
        content_hash = hash_file_contents(abs_path)
    except OSError as e:
        return WorkResult("read_error", file_id, abs_path_str, rel_path, filename, ext,
                           size, mtime, category, "failed", error_message=str(e))

    existing = _lookup_existing(file_id)
    if existing is not None and existing["content_hash"] == content_hash and existing["status"] != "pending":
        return WorkResult(
            "unchanged", file_id, abs_path_str, rel_path, filename, ext, size, mtime, category,
            existing["status"], content_hash=content_hash, reused=True,
            prior_extracted_text_path=existing["extracted_text_path"],
            ocr_used=bool(existing["ocr_used"]), ocr_confidence=existing["ocr_confidence"],
            sheet_names=json.loads(existing["sheet_names"]) if existing["sheet_names"] else None,
            tags=json.loads(existing["tags"]) if existing["tags"] else None,
            error_message=existing["error_message"],
        )

    try:
        result = extract(abs_path, category, ext, config)
    except Exception as e:
        # Safety net: an extractor bug/unhandled library exception on one file must
        # never abort the whole run (§7) — every extractor should already handle its
        # own expected failure modes, but this guarantees the invariant regardless.
        return WorkResult(
            "result", file_id, abs_path_str, rel_path, filename, ext, size, mtime, category, "failed",
            content_hash=content_hash,
            error_message=f"unhandled exception: {e}\n{traceback.format_exc()}",
        )

    prior_path = existing["extracted_text_path"] if existing is not None else None
    text = result.text if (result.status in _TEXT_STATUSES and result.text is not None) else None
    return WorkResult(
        "result", file_id, abs_path_str, rel_path, filename, ext, size, mtime, category, result.status,
        content_hash=content_hash, text=text, prior_extracted_text_path=prior_path,
        ocr_used=result.ocr_used, ocr_confidence=result.ocr_confidence,
        sheet_names=result.sheet_names, tags=result.tags, error_message=result.error_message,
    )


# --- Main-process side: logging, writing, manifest updates ------------------------

def _finalize(wr: WorkResult, config: Config, manifest: Manifest, registry: dict) -> str:
    if wr.kind == "permission_error":
        log.warning("PERMISSION_ERROR %s: %s", wr.rel_path, wr.error_message)
    elif wr.kind == "empty":
        log.info("EMPTY %s", wr.rel_path)
    elif wr.kind in ("excluded", "unclassified"):
        level = logging.DEBUG if wr.kind == "excluded" else logging.INFO
        log.log(level, "%s %s", wr.kind.upper(), wr.rel_path)
    elif wr.kind == "read_error":
        log.warning("READ_ERROR %s: %s", wr.rel_path, wr.error_message)
    elif wr.kind == "unchanged":
        log.debug("UNCHANGED %s", wr.rel_path)
    else:  # "result"
        if wr.ext == "xls" and wr.status == "extracted":
            log.warning("XLS_FIRST_SHEET_ONLY %s: legacy .xls conversion only exports the first sheet", wr.rel_path)
        if wr.error_message:
            log.warning("%s %s: %s", wr.status.upper(), wr.rel_path, wr.error_message)
        else:
            log.info("%s %s", wr.status.upper(), wr.rel_path)

    extracted_text_path = wr.prior_extracted_text_path if wr.reused else None
    if wr.kind == "result" and wr.text is not None:
        extracted_text_path = _write_extracted_text(
            config, wr.rel_path, wr.filename, wr.text,
            category=wr.category, ext=wr.ext, file_id=wr.file_id,
            prior_path=wr.prior_extracted_text_path, registry=registry,
        )

    manifest.upsert(_base_record(
        wr.file_id, wr.abs_path, wr.rel_path, wr.filename, wr.ext, wr.size, wr.mtime, wr.category, wr.status,
        content_hash=wr.content_hash,
        extracted_text_path=extracted_text_path,
        ocr_used=wr.ocr_used,
        ocr_confidence=wr.ocr_confidence,
        sheet_names=wr.sheet_names,
        tags=wr.tags,
        error_message=wr.error_message,
    ))
    return wr.status


def run(config: Config, manifest: Manifest, limit: int | None = None) -> dict:
    seen_file_ids: set[str] = set()
    processed = 0
    since_commit = 0
    registry = manifest.extracted_text_claims()

    def on_symlink(p: Path):
        log.info("SYMLINK_SKIPPED %s", p)

    entries = walk(config, on_symlink=on_symlink)

    with ProcessPoolExecutor(
        max_workers=config.max_workers,
        initializer=_init_worker,
        initargs=(config, str(config.manifest_db)),
    ) as executor:
        pending: set = set()

        def submit_next() -> bool:
            nonlocal processed
            if limit is not None and processed >= limit:
                return False
            try:
                entry = next(entries)
            except StopIteration:
                return False
            pending.add(executor.submit(_worker_task, str(entry.abs_path), entry.rel_path))
            processed += 1
            return True

        # Keep a bounded window of in-flight work — never materializes the full file
        # list in memory regardless of corpus size, and keeps every worker fed.
        for _ in range(config.max_workers * 4):
            if not submit_next():
                break

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                wr: WorkResult = fut.result()
                seen_file_ids.add(wr.file_id)
                _finalize(wr, config, manifest, registry)
                since_commit += 1
                if since_commit >= _COMMIT_BATCH:
                    manifest.commit()
                    since_commit = 0
                submit_next()

    manifest.commit()

    if limit is None:
        stale = manifest.all_file_ids() - seen_file_ids
        for file_id in stale:
            manifest.mark_deleted(file_id, _now())
        manifest.commit()
        if stale:
            log.info("DELETED %d file(s) no longer present on disk", len(stale))

    return {"processed": processed}
