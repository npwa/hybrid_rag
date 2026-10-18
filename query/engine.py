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
from query.generation import (
    GenerationError,
    build_general_knowledge_prompt,
    build_prompt,
    generate_answer_with_metrics,
    label_general_knowledge,
)
from query.relevance import has_relevant_results
from query.sparse import sparse_search

log = logging.getLogger("query")


@dataclass
class QueryResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    general_knowledge: bool = False
    # Populated only when a generation call actually happened — None on the
    # strict-grounding immediate-refusal path (query/relevance.py), since there's
    # nothing to measure. See scripts/benchmark_queries.py.
    total_seconds: float | None = None
    gen_tokens: int | None = None
    gen_seconds: float | None = None


def answer_query(query: str, config: QueryConfig) -> QueryResult:
    start = time.monotonic()

    try:
        vector = embed_batch([query], config)[0]
    except EmbeddingError as e:
        log.warning("QUERY_EMBED_FAILED %r: %s", query, e)
        return QueryResult(answer="", error=f"embedding failed: {e}")

    tbl = open_table(config)
    dense_results = dense_search(tbl, vector, config.top_n_dense)

    # Relevance gate (query/relevance.py): checked against the *raw* dense distances,
    # before fusion — RRF's fused score always looks normal even when nothing in the
    # corpus is actually relevant, since it's rank-based, not magnitude-based.
    relevant = has_relevant_results(dense_results, config.relevance_distance_threshold, config.relevance_min_hits)

    if not relevant and not config.allow_general_knowledge_fallback:
        # Default behavior: strict document-grounding, no LLM call needed since there's
        # nothing to ground an answer in (see Doc/step-5-requirements.md's design note).
        log.info("QUERY %r -> not relevant, fallback disabled", query)
        return QueryResult(answer="I couldn't find anything relevant to that in your indexed documents.")

    if not relevant and config.allow_general_knowledge_fallback:
        system, user = build_general_knowledge_prompt(query)
        try:
            gen = generate_answer_with_metrics(system, user, config)
        except GenerationError as e:
            log.warning("QUERY_GENERATION_FAILED %r: %s", query, e)
            return QueryResult(answer="", error=f"generation failed: {e}")
        answer = label_general_knowledge(gen.text)
        elapsed = time.monotonic() - start
        log.info("QUERY %r -> general-knowledge fallback, %.2fs", query, elapsed)
        gen_seconds = gen.eval_duration_ns / 1e9 if gen.eval_duration_ns else None
        return QueryResult(answer=answer, general_knowledge=True,
                            total_seconds=elapsed, gen_tokens=gen.eval_count, gen_seconds=gen_seconds)

    conn = sqlite3.connect(f"file:{config.manifest_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sparse_results = sparse_search(conn, config.fts5_table, query, config.top_n_sparse)
    finally:
        conn.close()

    fused = rrf_fuse([dense_results, sparse_results], k=config.rrf_k, top_k=config.top_k_fused,
                      list_names=["dense", "sparse"])

    system, user = build_prompt(query, fused)
    try:
        gen = generate_answer_with_metrics(system, user, config)
    except GenerationError as e:
        log.warning("QUERY_GENERATION_FAILED %r: %s", query, e)
        return QueryResult(answer="", error=f"generation failed: {e}")
    answer = gen.text

    # Which leg(s) actually found each source, and at what rank/score — not visible
    # from the fused list alone, since RRF's whole point is combining two differently-
    # scaled rankings into one. See run_query.py --scores for a human-readable table.
    sources = []
    for c in fused:
        ranks = c["_fusion_ranks"]
        sources.append({
            "rel_path": c["rel_path"],
            "chunk_id": c["chunk_id"],
            "branch": "+".join(n for n in ("dense", "sparse") if n in ranks),
            "rrf_score": round(c["_rrf_score"], 5),
            "dense_rank": ranks.get("dense"),
            "dense_distance": c.get("_distance"),
            "sparse_rank": ranks.get("sparse"),
            "sparse_bm25": c.get("score"),
        })
    elapsed = time.monotonic() - start
    log.info(
        "QUERY %r -> %d sources, %.2fs [%s]",
        query, len(sources), elapsed, ", ".join(s["rel_path"] for s in sources),
    )
    log.info(
        "QUERY %r fusion detail: %s", query,
        "; ".join(
            f"{s['rel_path']} branch={s['branch']} rrf={s['rrf_score']} "
            f"dense(rank={s['dense_rank']},dist={s['dense_distance']}) "
            f"sparse(rank={s['sparse_rank']},bm25={s['sparse_bm25']})"
            for s in sources
        ),
    )
    gen_seconds = gen.eval_duration_ns / 1e9 if gen.eval_duration_ns else None
    if gen.eval_count and gen_seconds:
        log.info("QUERY %r generation: %d tokens in %.2fs (%.1f tok/s)",
                  query, gen.eval_count, gen_seconds, gen.eval_count / gen_seconds)
    return QueryResult(answer=answer, sources=sources,
                        total_seconds=elapsed, gen_tokens=gen.eval_count, gen_seconds=gen_seconds)
