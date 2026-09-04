"""Per-run orchestration: pending chunks -> embed -> LanceDB + FTS5.

Concurrency model — deliberately different from Steps 1/3 (step-3-requirements.md §8's
process-pool pattern doesn't apply here): embedding is I/O-bound against a single Ollama
instance backed by one GPU, so there's no independent compute to parallelize across
processes — every request serializes on the same model/GPU regardless. The effective
lever is batching multiple chunks into one Ollama call (§5 of the Step 4 doc), not
process-level concurrency, so this runs single-process with batched sequential requests.
"""
from __future__ import annotations

import logging

from indexing.config import IndexConfig
from indexing.embedder import EmbeddingError, embed_batch
from indexing.vector_store import add_rows, delete_chunk_ids, open_or_create_table, rows_from_chunks
from ingest.manifest import Manifest

log = logging.getLogger("index")

_DELETE_BATCH = 500


def _row_to_dict(r) -> dict:
    return dict(r)


def run(config: IndexConfig, manifest: Manifest) -> dict:
    tbl = open_or_create_table(config)
    manifest.ensure_fts5(config.fts5_table)

    stats = {"embedded_chunks": 0, "embed_batches": 0, "embed_batch_failures": 0, "chunks_cleaned_up": 0}

    # --- 1. Embed and index every pending chunk, in batches ---
    after = ""
    while True:
        rows = manifest.chunks_by_status("pending", limit=config.embed_batch_size, after_chunk_id=after)
        if not rows:
            break
        after = rows[-1]["chunk_id"]
        chunk_dicts = [_row_to_dict(r) for r in rows]
        texts = [c["text"] for c in chunk_dicts]

        try:
            vectors = embed_batch(texts, config)
        except EmbeddingError as e:
            # Batch stays `pending` — retried on the next run (§5 of the Step 4 doc).
            # One bad batch must never abort the run, same invariant as Steps 1/3.
            log.warning("EMBED_BATCH_FAILED (%d chunks): %s", len(texts), e)
            stats["embed_batch_failures"] += 1
            continue

        add_rows(tbl, rows_from_chunks(chunk_dicts, vectors))
        fts_rows = [
            {"chunk_id": c["chunk_id"], "text": c["text"], "rel_path": c["rel_path"] or "", "tags": c["tags"] or ""}
            for c in chunk_dicts
        ]
        manifest.fts5_insert_batch(config.fts5_table, fts_rows)

        chunk_ids = [c["chunk_id"] for c in chunk_dicts]
        manifest.mark_chunks_embedded(chunk_ids)
        manifest.commit()

        stats["embedded_chunks"] += len(chunk_ids)
        stats["embed_batches"] += 1
        log.info("EMBEDDED batch of %d chunks (running total %d)", len(chunk_ids), stats["embedded_chunks"])

    # --- 2. Remove anything marked `deleted` (Step 3: source removed or changed) from
    #        both stores, then purge the now-fully-handled chunk row (§4, §5). ---
    while True:
        rows = manifest.chunks_by_status("deleted", limit=_DELETE_BATCH)
        if not rows:
            break
        chunk_ids = [r["chunk_id"] for r in rows]

        delete_chunk_ids(tbl, chunk_ids)
        manifest.fts5_delete_chunk_ids(config.fts5_table, chunk_ids)
        manifest.purge_chunks(chunk_ids)
        manifest.commit()

        stats["chunks_cleaned_up"] += len(chunk_ids)
        log.info("CLEANED_UP %d deleted chunk(s) from vector/FTS5 stores", len(chunk_ids))

    return stats
