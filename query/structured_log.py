"""Structured (JSONL) query log - Doc/step-9-requirements.md FR-3.5, plan decision D4.

One JSON object per answered/failed query appended to logs/query_YYYY-MM-DD.jsonl, next to
the human-readable text log (which is unchanged). Logging only: a failure to write must never
affect the answer, so every error is swallowed after a warning.

Record fields (all always present; unknown values are null):
  ts, query, caller (cli|http|mcp|unknown), outcome (answered|no_relevant|general_knowledge|error),
  error, n_sources, sources[], total_s, embed_s, retrieve_s, gen_s, gen_tokens, tok_per_s,
  distance_threshold, min_hits, schema (record version)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
OUTCOMES = ("answered", "no_relevant", "general_knowledge", "error")

_lock = threading.Lock()
log = logging.getLogger("query")


def jsonl_path(logs_dir: Path, when: datetime | None = None) -> Path:
    return Path(logs_dir) / f"query_{(when or datetime.now()).date().isoformat()}.jsonl"


def log_query_event(config, query: str, caller: str, outcome: str, *, error: str | None = None,
                    sources: list[dict] | None = None, total_s: float | None = None,
                    embed_s: float | None = None, retrieve_s: float | None = None,
                    gen_s: float | None = None, gen_tokens: int | None = None,
                    tok_per_s: float | None = None) -> None:
    now = datetime.now()
    record = {
        "schema": SCHEMA_VERSION,
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "query": query,
        "caller": caller,
        "outcome": outcome,
        "error": error,
        "n_sources": len(sources or []),
        "sources": sources or [],
        "total_s": _r(total_s), "embed_s": _r(embed_s), "retrieve_s": _r(retrieve_s), "gen_s": _r(gen_s),
        "gen_tokens": gen_tokens, "tok_per_s": _r(tok_per_s),
        "distance_threshold": getattr(config, "relevance_distance_threshold", None),
        "min_hits": getattr(config, "relevance_min_hits", None),
    }
    try:
        path = jsonl_path(config.logs_dir, now)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:   # never let logging break a query
        log.warning("STRUCTURED_LOG_FAILED: %s", e)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)
