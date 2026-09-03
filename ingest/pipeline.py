"""Per-run orchestration: walk -> classify -> hash -> extract -> manifest.

Idempotency (§8): every file's content_hash is recomputed each run and
compared against the stored value (not mtime, which can change without the
content changing). Unchanged files are a no-op; only new or changed files
are (re-)extracted. Files no longer present on disk are marked `deleted`
rather than removed from the manifest, preserving history (§5).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path, PurePosixPath

from ingest.classify import classify, extension_of
from ingest.config import Config
from ingest.extractors import ExtractionResult, extract
from ingest.hashing import hash_file_contents, hash_path
from ingest.manifest import FileRecord, Manifest
from ingest.walker import walk

log = logging.getLogger("ingest")

# Statuses that indicate we have usable extracted text worth writing to disk.
_TEXT_STATUSES = {"extracted", "ocr_extracted", "ocr_low_confidence"}


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


def process_file(abs_path: Path, rel_path: str, config: Config, manifest: Manifest, registry: dict) -> str:
    filename = abs_path.name
    ext = extension_of(filename)
    file_id = hash_path(str(abs_path))
    category = classify(filename, config)

    try:
        st = abs_path.stat()
    except OSError as e:
        log.warning("PERMISSION_ERROR %s: %s", rel_path, e)
        manifest.upsert(_base_record(
            file_id, abs_path, rel_path, filename, ext, 0, "", category, "failed",
            error_message=str(e),
        ))
        return "failed"

    size = st.st_size
    mtime = datetime.fromtimestamp(st.st_mtime).isoformat()

    if size == 0:
        log.info("EMPTY %s", rel_path)
        manifest.upsert(_base_record(file_id, abs_path, rel_path, filename, ext, size, mtime, category, "empty"))
        return "empty"

    if category in ("excluded", "unclassified"):
        level = logging.DEBUG if category == "excluded" else logging.INFO
        log.log(level, "%s %s", category.upper(), rel_path)
        manifest.upsert(_base_record(file_id, abs_path, rel_path, filename, ext, size, mtime, category, "skipped"))
        return "skipped"

    # category is "include" or "readme" from here on — compute content hash for change detection.
    try:
        content_hash = hash_file_contents(abs_path)
    except OSError as e:
        log.warning("READ_ERROR %s: %s", rel_path, e)
        manifest.upsert(_base_record(
            file_id, abs_path, rel_path, filename, ext, size, mtime, category, "failed",
            error_message=str(e),
        ))
        return "failed"

    existing = manifest.get(file_id)
    if existing is not None and existing["content_hash"] == content_hash and existing["status"] != "pending":
        log.debug("UNCHANGED %s", rel_path)
        manifest.upsert(_base_record(
            file_id, abs_path, rel_path, filename, ext, size, mtime, category, existing["status"],
            content_hash=content_hash,
            extracted_text_path=existing["extracted_text_path"],
            ocr_used=bool(existing["ocr_used"]),
            ocr_confidence=existing["ocr_confidence"],
            sheet_names=json.loads(existing["sheet_names"]) if existing["sheet_names"] else None,
            tags=json.loads(existing["tags"]) if existing["tags"] else None,
            error_message=existing["error_message"],
        ))
        return existing["status"]

    try:
        result = extract(abs_path, category, ext, config)
    except Exception as e:
        # Safety net: an extractor bug/unhandled library exception on one file must
        # never abort the whole run (§7) — every extractor should already handle its
        # own expected failure modes, but this guarantees the invariant regardless.
        log.exception("UNHANDLED_EXTRACTION_ERROR %s", rel_path)
        result = ExtractionResult(status="failed", error_message=f"unhandled exception: {e}")

    if ext == "xls" and result.status == "extracted":
        log.warning("XLS_FIRST_SHEET_ONLY %s: legacy .xls conversion only exports the first sheet", rel_path)

    extracted_text_path = None
    if result.status in _TEXT_STATUSES and result.text is not None:
        prior_path = existing["extracted_text_path"] if existing is not None else None
        extracted_text_path = _write_extracted_text(
            config, rel_path, filename, result.text,
            category=category, ext=ext, file_id=file_id, prior_path=prior_path, registry=registry,
        )

    if result.error_message:
        log.warning("%s %s: %s", result.status.upper(), rel_path, result.error_message)
    else:
        log.info("%s %s", result.status.upper(), rel_path)

    manifest.upsert(_base_record(
        file_id, abs_path, rel_path, filename, ext, size, mtime, category, result.status,
        content_hash=content_hash,
        extracted_text_path=extracted_text_path,
        ocr_used=result.ocr_used,
        ocr_confidence=result.ocr_confidence,
        sheet_names=result.sheet_names,
        tags=result.tags,
        error_message=result.error_message,
    ))
    return result.status


def run(config: Config, manifest: Manifest, limit: int | None = None) -> dict:
    seen_file_ids: set[str] = set()
    processed = 0
    registry = manifest.extracted_text_claims()

    def on_symlink(p: Path):
        log.info("SYMLINK_SKIPPED %s", p)

    for entry in walk(config, on_symlink=on_symlink):
        if limit is not None and processed >= limit:
            break
        file_id = hash_path(str(entry.abs_path))
        seen_file_ids.add(file_id)
        process_file(entry.abs_path, entry.rel_path, config, manifest, registry)
        processed += 1

    if limit is None:
        stale = manifest.all_file_ids() - seen_file_ids
        for file_id in stale:
            manifest.mark_deleted(file_id, _now())
        if stale:
            log.info("DELETED %d file(s) no longer present on disk", len(stale))

    return {"processed": processed}
