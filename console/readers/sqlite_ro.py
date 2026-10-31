"""Read-only SQLite access to manifest.db (requirement C2): URI mode=ro plus PRAGMA query_only."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from console.failures import PROBLEM_STATUSES, classify_problem, cause_info, outcome_group


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


def summary(conn: sqlite3.Connection) -> dict:
    """Page 1 headline numbers (FR-1.1, FR-1.2): counts by status, outcome group and extension."""
    base = index_counts(conn)
    groups = {"indexed": 0, "failed": 0, "needs_attention": 0, "skipped": 0, "other": 0}
    for st, n in base["files_by_status"].items():
        groups[outcome_group(st)] += n
    attempted = groups["indexed"] + groups["failed"] + groups["needs_attention"] + groups["other"]
    matrix: dict[str, dict[str, int]] = {}
    for ext, st, n in conn.execute("SELECT COALESCE(extension,''), status, COUNT(*) FROM files GROUP BY 1, 2"):
        row = matrix.setdefault(ext, {"indexed": 0, "failed": 0, "needs_attention": 0, "skipped": 0, "other": 0})
        row[outcome_group(st)] += n
    by_ext = sorted(({"extension": e, **g, "total": sum(g.values())} for e, g in matrix.items()),
                    key=lambda r: (-r["total"], r["extension"]))
    top, rest = by_ext[:12], by_ext[12:]
    if rest:
        agg = {"extension": "(other types)", "indexed": 0, "failed": 0, "needs_attention": 0, "skipped": 0, "other": 0}
        for r in rest:
            for k in ("indexed", "failed", "needs_attention", "skipped", "other"):
                agg[k] += r[k]
        agg["total"] = sum(agg[k] for k in ("indexed", "failed", "needs_attention", "skipped", "other"))
        top.append(agg)
    causes: dict[str, int] = {}
    for st, msg, fn in conn.execute(
            f"SELECT status, error_message, filename FROM files WHERE status IN ({','.join('?' * len(PROBLEM_STATUSES))})",
            PROBLEM_STATUSES):
        c = classify_problem(st, msg, fn)
        causes[c] = causes.get(c, 0) + 1
    problems = [{**cause_info(c), "count": n} for c, n in sorted(causes.items(), key=lambda kv: -kv[1])]
    return {
        **{k: v for k, v in base.items() if k != "files_by_extension"},
        "outcome_groups": groups,
        "attempted": attempted,
        "percent_indexed": round(100 * groups["indexed"] / attempted, 1) if attempted else None,
        "percent_failed": round(100 * groups["failed"] / attempted, 1) if attempted else None,
        "files_by_type": top,
        "problems_by_cause": problems,
    }


FAILURE_SORTS = {"path": "rel_path", "extension": "extension", "status": "status", "size": "size_bytes",
                 "ocr_confidence": "ocr_confidence", "processed": "last_processed"}


def failures(conn: sqlite3.Connection, *, cause: str | None = None, extension: str | None = None,
             status: str | None = None, q: str | None = None, sort: str = "path", desc: bool = False,
             limit: int = 50, offset: int = 0, mask: bool = False) -> dict:
    """Paginated list of problem files with cause category (FR-1.4, FR-1.5)."""
    from console.failures import mask_message, mask_path
    rows = conn.execute(
        f"SELECT file_id, rel_path, filename, extension, size_bytes, status, ocr_confidence, error_message, last_processed "
        f"FROM files WHERE status IN ({','.join('?' * len(PROBLEM_STATUSES))})", PROBLEM_STATUSES).fetchall()
    items = []
    for r in rows:
        c = classify_problem(r["status"], r["error_message"], r["filename"])
        if cause and c != cause:
            continue
        if extension is not None and (r["extension"] or "") != extension:
            continue
        if status and r["status"] != status:
            continue
        if q and q.lower() not in (r["rel_path"] or "").lower():
            continue
        items.append({
            "file_id": r["file_id"], "rel_path": mask_path(r["rel_path"]) if mask else r["rel_path"],
            "extension": r["extension"] or "", "size_bytes": r["size_bytes"], "status": r["status"],
            "ocr_confidence": r["ocr_confidence"],
            "error_message": mask_message(r["error_message"]) if mask else r["error_message"],
            "last_processed": r["last_processed"], **cause_info(c)})
    key = {"path": "rel_path", "extension": "extension", "status": "status", "size": "size_bytes",
           "ocr_confidence": "ocr_confidence", "processed": "last_processed", "cause": "cause"}.get(sort, "rel_path")
    items.sort(key=lambda i: (i[key] is None, i[key] if i[key] is not None else 0), reverse=desc)
    return {"total": len(items), "limit": limit, "offset": offset, "items": items[offset:offset + limit]}
