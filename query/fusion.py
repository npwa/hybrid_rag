"""Reciprocal Rank Fusion — step-5-requirements.md §2 step 3."""
from __future__ import annotations


def rrf_fuse(
    result_lists: list[list[dict]], k: int, top_k: int, list_names: list[str] | None = None
) -> list[dict]:
    """Each inner list is already ranked (best first). score = sum(1/(k+rank)) across
    every list a chunk_id appears in; only rank position matters, not the underlying
    metric (cosine/L2 distance for dense, bm25() for sparse — not comparable to each
    other, which is exactly the problem RRF sidesteps).

    `list_names` (e.g. ["dense", "sparse"]) labels which leg(s) each returned chunk
    actually came from — added so a caller can show *why* a source was picked (which
    leg(s) found it, at what rank, and its raw per-leg score) rather than just the
    final fused list, which on its own doesn't say whether a source came from dense
    similarity, keyword match, or both. Each returned dict keeps every field from the
    original chunk records (merged across legs — dense's `_distance` and sparse's
    `score` use different key names, so both survive when a chunk appears in both),
    plus two new ones: `_rrf_score` (the fused score that determined ranking) and
    `_fusion_ranks` (e.g. `{"dense": 2}` or `{"dense": 5, "sparse": 1}` — the 1-based
    rank within each leg that returned this chunk; a leg absent from this dict never
    returned the chunk at all)."""
    names = list_names or [f"list{i}" for i in range(len(result_lists))]
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    fusion_ranks: dict[str, dict[str, int]] = {}
    for name, results in zip(names, result_lists):
        for rank, item in enumerate(results, start=1):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            meta.setdefault(cid, {}).update(item)
            fusion_ranks.setdefault(cid, {})[name] = rank

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
    out = []
    for cid in ranked_ids:
        row = dict(meta[cid])
        row["_rrf_score"] = scores[cid]
        row["_fusion_ranks"] = fusion_ranks[cid]
        out.append(row)
    return out
