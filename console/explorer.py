"""Query explorer backend (requirements FR-2.x): shows how retrieval reached its ranking without touching the
production logs. Retrieval itself is query.engine.retrieve(), the same function production answers use (FR-2.6).

The engine is imported lazily so the console process stays light until the explorer is used."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from console.config import ConsoleConfig

EXCERPT_CHARS = 320
DEMO_DISTANCE_THRESHOLD = 1.35      # the demo embedder is hashed bag-of-words, not nomic: its distances live on another scale

_busy = threading.Lock()           # one exploration at a time: embedding and generation share the GPU with Signal answers


class Busy(Exception):
    pass


def build_query_config(cfg: ConsoleConfig):
    """The engine's QueryConfig; in demo mode pointed at the synthetic dataset."""
    from query.config import QueryConfig
    q = QueryConfig.load(cfg.query_config)
    if cfg.demo:
        q.working_dir = cfg.working_dir
        q.manifest_db = cfg.manifest_db
        q.lancedb_dir = cfg.lancedb_dir
        q.lancedb_table = cfg.lancedb_table
        q.logs_dir = cfg.logs_dir
        q.relevance_distance_threshold = DEMO_DISTANCE_THRESHOLD
    return q


def _excerpt(text: str | None, mask: bool) -> str:
    if mask:
        return "[masked]"
    t = " ".join((text or "").split())
    return t if len(t) <= EXCERPT_CHARS else t[:EXCERPT_CHARS].rstrip() + "…"


def _path(p: str | None, mask: bool) -> str:
    from console.failures import mask_path
    return mask_path(p or "") if mask else (p or "")


def explain_gate(q, r) -> dict:
    thr, need = q.relevance_distance_threshold, q.relevance_min_hits
    nearest = r.dense[0]["_distance"] if r.dense else None
    if r.relevant:
        why = (f"{r.hits} of the top {len(r.dense)} dense hits are closer than {thr} (the gate needs at least {need}), "
               f"so the question is treated as answerable from your documents.")
        outcome = "answered"
    elif q.allow_general_knowledge_fallback:
        why = (f"Only {r.hits} dense hit(s) are closer than {thr}, but the gate needs {need}. The general-knowledge "
               f"fallback is on, so production would answer from the model's own knowledge, labelled as such.")
        outcome = "general_knowledge"
    else:
        why = (f"Only {r.hits} dense hit(s) are closer than {thr}, but the gate needs {need}. Production would not "
               f"call the language model and would reply \"I couldn't find anything relevant…\".")
        outcome = "no_relevant"
    return {"relevant": r.relevant, "hits": r.hits, "required_hits": need, "distance_threshold": thr,
            "nearest_distance": nearest, "production_outcome": outcome, "explanation": why,
            "would_pass_with_min_hits": {str(m): r.hits >= m for m in (1, 2, 3, 4, 5)}}


def explore(cfg: ConsoleConfig, query: str, *, generate: bool = False, embed=None, qcfg=None) -> dict:
    if not _busy.acquire(blocking=False):
        raise Busy()
    try:
        return _explore(cfg, query, generate, embed, qcfg)
    finally:
        _busy.release()


def _explore(cfg: ConsoleConfig, query: str, generate: bool, embed, qcfg) -> dict:
    from query.engine import retrieve
    q = qcfg or build_query_config(cfg)
    if embed is None and cfg.demo:
        from console.demo_embed import embed_batch as embed
    mask = cfg.mask_queries
    t0 = time.monotonic()
    r = retrieve(query, q, full=True, embed=embed)          # EmbeddingError propagates to the API layer
    fused_ids = {c["chunk_id"] for c in r.fused}
    dense_ids = {c["chunk_id"] for c in r.dense}
    sparse_ids = {c["chunk_id"] for c in r.sparse}

    dense = [{"rank": i, "chunk_id": c["chunk_id"], "rel_path": _path(c.get("rel_path"), mask),
              "distance": c["_distance"], "passes_threshold": c["_distance"] < q.relevance_distance_threshold,
              "in_fused": c["chunk_id"] in fused_ids, "also_sparse": c["chunk_id"] in sparse_ids,
              "excerpt": _excerpt(c.get("text"), mask)} for i, c in enumerate(r.dense, start=1)]
    sparse = [{"rank": i, "chunk_id": c["chunk_id"], "rel_path": _path(c.get("rel_path"), mask), "bm25": c["score"],
               "in_fused": c["chunk_id"] in fused_ids, "also_dense": c["chunk_id"] in dense_ids,
               "excerpt": _excerpt(c.get("text"), mask)} for i, c in enumerate(r.sparse, start=1)]
    fused = []
    for i, c in enumerate(r.fused, start=1):
        ranks = c["_fusion_ranks"]
        fused.append({"rank": i, "chunk_id": c["chunk_id"], "rel_path": _path(c.get("rel_path"), mask),
                      "rrf_score": round(c["_rrf_score"], 5), "branch": "+".join(n for n in ("dense", "sparse") if n in ranks),
                      "dense_rank": ranks.get("dense"), "dense_distance": c.get("_distance"),
                      "sparse_rank": ranks.get("sparse"), "sparse_bm25": c.get("score"),
                      "excerpt": _excerpt(c.get("text"), mask)})

    gate = explain_gate(q, r)
    timings = {k: round(v, 4) for k, v in r.timings.items()}
    answer = gen_error = None
    if generate:
        answer, gen_error, timings["generate_s"] = _generate(cfg, q, query, r, gate)
    timings["total_s"] = round(time.monotonic() - t0, 4)

    out = {
        "query": query, "demo": cfg.demo, "generated": generate,
        "settings": {"top_n_dense": q.top_n_dense, "top_n_sparse": q.top_n_sparse, "rrf_k": q.rrf_k,
                     "top_k_fused": q.top_k_fused, "distance_threshold": q.relevance_distance_threshold,
                     "min_hits": q.relevance_min_hits, "allow_general_knowledge": q.allow_general_knowledge_fallback},
        "gate": gate, "dense": dense, "sparse": sparse, "fused": fused, "timings": timings,
        "answer": None if (mask and answer) else answer, "generation_error": gen_error,
    }
    _log(cfg, out)
    return out


def _generate(cfg, q, query, r, gate):
    """Mirrors answer_query's branches but logs nothing to the production logs (FR-2.5)."""
    if cfg.demo:
        return None, "generation is not available in demo mode (no language model is connected)", 0.0
    from query.generation import (GenerationError, build_general_knowledge_prompt, build_prompt, generate_answer,
                                  label_general_knowledge)
    t = time.monotonic()
    try:
        if r.relevant:
            system, user = build_prompt(query, r.fused)
            ans = generate_answer(system, user, q)
        elif q.allow_general_knowledge_fallback:
            system, user = build_general_knowledge_prompt(query)
            ans = label_general_knowledge(generate_answer(system, user, q))
        else:
            ans = "I couldn't find anything relevant to that in your indexed documents."
        return ans, None, round(time.monotonic() - t, 4)
    except GenerationError as e:
        return None, f"generation failed: {e}", round(time.monotonic() - t, 4)


def explorer_log_path(cfg: ConsoleConfig, when: datetime | None = None) -> Path:
    return cfg.logs_dir / "explorer" / f"explore_{(when or datetime.now()).date().isoformat()}.jsonl"


def _log(cfg: ConsoleConfig, out: dict) -> None:
    """Explorer runs are recorded apart from production (FR-2.5): never in query_*.log or query_*.jsonl."""
    try:
        now = datetime.now()
        path = explorer_log_path(cfg, now)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "caller": "console-explorer", "query": out["query"],
               "generated": out["generated"], "relevant": out["gate"]["relevant"], "n_dense": len(out["dense"]),
               "n_sparse": len(out["sparse"]), "n_fused": len(out["fused"]), "timings": out["timings"]}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass       # an unwritable log directory must not break the explorer (the console is read-only by design)
