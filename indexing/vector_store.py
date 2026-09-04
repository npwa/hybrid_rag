"""LanceDB (dense leg) — step-4-requirements.md §2b."""
from __future__ import annotations

import lancedb

from indexing.config import IndexConfig

_SCHEMA_COLUMNS = [
    "chunk_id", "vector", "file_id", "rel_path", "category", "extension",
    "tags", "sheet_name", "ocr_used", "ocr_confidence", "text",
]


def open_or_create_table(config: IndexConfig):
    db = lancedb.connect(str(config.lancedb_dir))
    if config.lancedb_table in db.table_names():
        return db.open_table(config.lancedb_table)

    # Seed row to establish the schema (dropped immediately after) — LanceDB infers
    # column types from the first batch of data rather than an explicit schema API.
    seed = [{
        "chunk_id": "", "vector": [0.0] * config.embed_dim, "file_id": "", "rel_path": "",
        "category": "", "extension": "", "tags": "", "sheet_name": "", "ocr_used": False,
        "ocr_confidence": 0.0, "text": "",
    }]
    tbl = db.create_table(config.lancedb_table, data=seed, mode="overwrite")
    tbl.delete("chunk_id = ''")
    return tbl


def rows_from_chunks(chunk_rows: list[dict], vectors: list[list[float]]) -> list[dict]:
    """`chunk_rows` come straight from the `chunks` SQLite table, where `tags` is
    already a JSON-encoded string (Step 3's ChunkRecord.as_row()) — passed through
    as-is here, not re-encoded."""
    rows = []
    for c, vec in zip(chunk_rows, vectors):
        rows.append({
            "chunk_id": c["chunk_id"],
            "vector": vec,
            "file_id": c["file_id"],
            "rel_path": c["rel_path"] or "",
            "category": c["category"] or "",
            "extension": c["extension"] or "",
            "tags": c["tags"] or "",
            "sheet_name": c["sheet_name"] or "",
            "ocr_used": bool(c["ocr_used"]),
            "ocr_confidence": c["ocr_confidence"] if c["ocr_confidence"] is not None else 0.0,
            "text": c["text"],
        })
    return rows


def add_rows(tbl, rows: list[dict]) -> None:
    if rows:
        tbl.add(rows)


def delete_chunk_ids(tbl, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    quoted = ", ".join("'" + cid.replace("'", "''") + "'" for cid in chunk_ids)
    tbl.delete(f"chunk_id IN ({quoted})")
