"""The interface-agnostic core query engine — step-5-requirements.md §2.

No HTTP, no CLI parsing, no Signal-specific code lives here (§2's own stated
requirement) — this module is imported directly by the CLI (run_query.py) and the
HTTP server (query/server.py) alike.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field

from indexing.embedder import EmbeddingError, embed_batch
from query.config import QueryConfig
from query.dense import dense_search, open_table
from query.fusion import rrf_fuse
from query.generation import GenerationError, build_prompt, generate_answer
from query.sparse import sparse_search

log = logging.getLogger("query")


@dataclass
class QueryResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    error: str | None = None


def answer_query(query: str, config: QueryConfig) -> QueryResult:
    start = time.monotonic()

    try:
        vector = embed_batch([query], config)[0]
    except EmbeddingError as e:
        log.warning("QUERY_EMBED_FAILED %r: %s", query, e)
        return QueryResult(answer="", error=f"embedding failed: {e}")

    tbl = open_table(config)
    dense_results = dense_search(tbl, vector, config.top_n_dense)

    conn = sqlite3.connect(f"file:{config.manifest_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sparse_results = sparse_search(conn, config.fts5_table, query, config.top_n_sparse)
    finally:
        conn.close()

    fused = rrf_fuse([dense_results, sparse_results], k=config.rrf_k, top_k=config.top_k_fused)
    if not fused:
        log.info("QUERY %r -> no results", query)
        return QueryResult(answer="I couldn't find anything relevant in the indexed documents.")

    system, user = build_prompt(query, fused)
    try:
        answer = generate_answer(system, user, config)
    except GenerationError as e:
        log.warning("QUERY_GENERATION_FAILED %r: %s", query, e)
        return QueryResult(answer="", error=f"generation failed: {e}")

    sources = [{"rel_path": c["rel_path"], "chunk_id": c["chunk_id"]} for c in fused]
    elapsed = time.monotonic() - start
    log.info(
        "QUERY %r -> %d sources, %.2fs [%s]",
        query, len(sources), elapsed, ", ".join(s["rel_path"] for s in sources),
    )
    return QueryResult(answer=answer, sources=sources)
