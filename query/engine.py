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
    generate_answer,
    label_general_knowledge,
)
from query.relevance import has_relevant_results
from query.sparse import sparse_search
from query.structured_log import log_query_event

log = logging.getLogger("query")


@dataclass
class QueryResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    general_knowledge: bool = False


@dataclass
class Retrieval:
    """Everything retrieval produced, before any generation. Shared by answer_query() (production) and the
    operator console's query explorer, so both always see the same ranking (Doc/step-9-requirements.md FR-2.6)."""
    vector: list[float]
    dense: list[dict]
    relevant: bool                  # the relevance gate (query/relevance.py) on the raw dense distances
    hits: int                       # dense results under the distance threshold
    sparse: list[dict] | None       # None when skipped (not relevant and full=False)
    fused: list[dict] | None        # None when skipped
    timings: dict = field(default_factory=dict)   # embed_s, dense_s, sparse_s, fuse_s (seconds)


def retrieve(query: str, config: QueryConfig, *, full: bool = False, embed=None) -> Retrieval:
    """Embed, dense search, relevance gate, then (if relevant, or `full`) keyword search and RRF fusion.

    Production passes full=False, so a query the corpus has nothing on stops after the gate exactly as before
    (no keyword search). The explorer passes full=True to show every stage. `embed` replaces the embedding call
    (demo mode and tests). Raises EmbeddingError if embedding fails."""
    t0 = time.monotonic()
    vector = (embed or embed_batch)([query], config)[0]
    t1 = time.monotonic()
    tbl = open_table(config)
    dense_results = dense_search(tbl, vector, config.top_n_dense)
    t2 = time.monotonic()

    # Relevance gate (query/relevance.py): checked against the *raw* dense distances,
    # before fusion — RRF's fused score always looks normal even when nothing in the
    # corpus is actually relevant, since it's rank-based, not magnitude-based.
    relevant = has_relevant_results(dense_results, config.relevance_distance_threshold, config.relevance_min_hits)
    hits = sum(1 for r in dense_results if r["_distance"] < config.relevance_distance_threshold)
    timings = {"embed_s": t1 - t0, "dense_s": t2 - t1}
    if not relevant and not full:
        return Retrieval(vector, dense_results, relevant, hits, None, None, timings)

    conn = sqlite3.connect(f"file:{config.manifest_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sparse_results = sparse_search(conn, config.fts5_table, query, config.top_n_sparse)
    finally:
        conn.close()
    t3 = time.monotonic()
    fused = rrf_fuse([dense_results, sparse_results], k=config.rrf_k, top_k=config.top_k_fused,
                     list_names=["dense", "sparse"])
    timings.update(sparse_s=t3 - t2, fuse_s=time.monotonic() - t3)
    return Retrieval(vector, dense_results, relevant, hits, sparse_results, fused, timings)


def answer_query(query: str, config: QueryConfig, caller: str = "unknown") -> QueryResult:
    """`caller` (cli | http | mcp) only labels the structured JSONL log; it never affects results."""
    start = time.monotonic()

    try:
        r = retrieve(query, config)
    except EmbeddingError as e:
        log.warning("QUERY_EMBED_FAILED %r: %s", query, e)
        log_query_event(config, query, caller, "error", error=f"embedding failed: {e}", total_s=time.monotonic() - start)
        return QueryResult(answer="", error=f"embedding failed: {e}")
    embed_s = r.timings["embed_s"]
    relevant = r.relevant

    if not relevant and not config.allow_general_knowledge_fallback:
        # Default behavior: strict document-grounding, no LLM call needed since there's
        # nothing to ground an answer in (see Doc/step-5-requirements.md's design note).
        log.info("QUERY %r -> not relevant, fallback disabled", query)
        log_query_event(config, query, caller, "no_relevant", total_s=time.monotonic() - start, embed_s=embed_s,
                        retrieve_s=time.monotonic() - start - embed_s)
        return QueryResult(answer="I couldn't find anything relevant to that in your indexed documents.")

    if not relevant and config.allow_general_knowledge_fallback:
        system, user = build_general_knowledge_prompt(query)
        try:
            answer = generate_answer(system, user, config)
        except GenerationError as e:
            log.warning("QUERY_GENERATION_FAILED %r: %s", query, e)
            log_query_event(config, query, caller, "error", error=f"generation failed: {e}", total_s=time.monotonic() - start)
            return QueryResult(answer="", error=f"generation failed: {e}")
        answer = label_general_knowledge(answer)
        elapsed = time.monotonic() - start
        log.info("QUERY %r -> general-knowledge fallback, %.2fs", query, elapsed)
        log_query_event(config, query, caller, "general_knowledge", total_s=elapsed, embed_s=embed_s)
        return QueryResult(answer=answer, general_knowledge=True)

    fused = r.fused

    retrieved_at = time.monotonic()
    system, user = build_prompt(query, fused)
    try:
        answer = generate_answer(system, user, config)
    except GenerationError as e:
        log.warning("QUERY_GENERATION_FAILED %r: %s", query, e)
        log_query_event(config, query, caller, "error", error=f"generation failed: {e}", total_s=time.monotonic() - start)
        return QueryResult(answer="", error=f"generation failed: {e}")

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
    log_query_event(config, query, caller, "answered", sources=sources, total_s=elapsed, embed_s=embed_s,
                    retrieve_s=retrieved_at - start - embed_s, gen_s=time.monotonic() - retrieved_at)
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
    return QueryResult(answer=answer, sources=sources)
