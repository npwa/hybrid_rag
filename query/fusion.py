"""Reciprocal Rank Fusion — step-5-requirements.md §2 step 3."""
from __future__ import annotations


def rrf_fuse(result_lists: list[list[dict]], k: int, top_k: int) -> list[dict]:
    """Each inner list is already ranked (best first). score = sum(1/(k+rank)) across
    every list a chunk_id appears in; only rank position matters, not the underlying
    metric (cosine/L2 distance for dense, bm25() for sparse — not comparable to each
    other, which is exactly the problem RRF sidesteps)."""
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for results in result_lists:
        for rank, item in enumerate(results, start=1):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            meta.setdefault(cid, item)

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
    return [meta[cid] for cid in ranked_ids]
