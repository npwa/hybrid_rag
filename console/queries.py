"""Page 3: aggregates over the query logs (FR-3.1 to FR-3.6). One QueryEvent list per day comes from
readers.query_log (JSONL when the day has it, else the text log); everything here is pure computation on it.

Definitions (also in Doc/console-guide.md):
  user query    a question not starting with "### Task:" (Open WebUI's automatic title/follow-up prompts are `system`)
  latency       total seconds of answered + general-knowledge queries (errors are counted, not timed)
  no_relevant   the relevance gate refused: nothing close enough, general knowledge disabled
  zero sources  any query that ended with no source documents (no_relevant, general knowledge, error)
  slow          total seconds >= the slow threshold (config slow_query_seconds, default 30)
  error         embedding or generation failed (including timeouts)
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta

from console.config import ConsoleConfig
from console.failures import mask_message, mask_path, mask_text
from console.readers import query_log
from console.readers.agent_log import _stats

STOPWORDS = frozenset("""a about all also an and any are as at be been by can could did do does for from get had has have how i if in into is it
its me my of on or our so than that the their them then there these they this to us was we were what when where which who whom why will with
would you your give list show tell find please""".split())
_WORD = re.compile(r"[a-z][a-z0-9'-]{2,}")


def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower()).rstrip("?!. ")


def terms(q: str) -> set[str]:
    return {w.strip("'-") for w in _WORD.findall(q.lower()) if w not in STOPWORDS}


def load(config: ConsoleConfig, days: int) -> tuple[list, dict[str, str]]:
    """All events of the last `days` days (including today) and, per day, which log format was used."""
    events, fmt = [], {}
    for i in range(days - 1, -1, -1):
        day = (config.now().date() - timedelta(days=i)).isoformat()
        evs = query_log.read_day(config.logs_dir, day)
        if evs:
            events += evs
            fmt[day] = evs[0].source_format
    return events, fmt


def _rate(n: int, d: int):
    return None if not d else round(100 * n / d, 1)


def stats(config: ConsoleConfig, days: int, slow_seconds: float | None = None, top: int = 10) -> dict:
    slow_s = config.slow_query_seconds if slow_seconds is None else slow_seconds
    events, fmt = load(config, days)
    user = [e for e in events if not e.is_system]
    system = [e for e in events if e.is_system]
    mask = config.mask_queries

    timed = [e for e in user if e.outcome in ("answered", "general_knowledge") and e.total_s is not None]
    by_outcome = Counter(e.outcome for e in user)
    totals = {
        "queries": len(user), "system_queries": len(system), "by_outcome": {k: by_outcome.get(k, 0) for k in ("answered", "no_relevant", "general_knowledge", "error")},
        "zero_sources": sum(1 for e in user if e.n_sources == 0),
        "timed": len(timed), "slow": sum(1 for e in timed if e.total_s >= slow_s),
    }
    rates = {"no_relevant": _rate(totals["by_outcome"]["no_relevant"], len(user)),
             "general_knowledge": _rate(totals["by_outcome"]["general_knowledge"], len(user)),
             "error": _rate(totals["by_outcome"]["error"], len(user)),
             "zero_sources": _rate(totals["zero_sources"], len(user)),
             "slow": _rate(totals["slow"], len(timed))}

    per_day: dict[str, list] = defaultdict(list)
    for e in user:
        per_day[e.ts[:10]].append(e)
    series = []
    for day in sorted(per_day):
        evs = per_day[day]
        lat = [e.total_s for e in evs if e.outcome in ("answered", "general_knowledge") and e.total_s is not None]
        tps = [e.tok_per_s for e in evs if e.tok_per_s]
        c = Counter(e.outcome for e in evs)
        series.append({"day": day, "queries": len(evs), "answered": c["answered"], "no_relevant": c["no_relevant"],
                       "general_knowledge": c["general_knowledge"], "error": c["error"],
                       "slow": sum(1 for s in lat if s >= slow_s), "latency_s": _stats(lat),
                       "tok_per_s": _stats(tps)["p50"], "format": fmt.get(day)})

    callers = Counter((e.caller or "unknown") for e in user)
    groups: dict[str, list] = defaultdict(list)
    for e in user:
        groups[normalize(e.query)].append(e)
    recurring = sorted(((k, v) for k, v in groups.items() if len(v) >= 2), key=lambda kv: (-len(kv[1]), kv[0]))[:top]
    top_queries = [{"query": mask_text(v[0].query) if mask else v[0].query, "count": len(v), "last_seen": max(e.ts for e in v),
                    "no_relevant": sum(1 for e in v if e.outcome == "no_relevant"), "errors": sum(1 for e in v if e.outcome == "error")}
                   for _, v in recurring]
    tc: Counter = Counter()
    for e in user:
        tc.update(terms(e.query))
    top_terms = [] if mask else [{"term": t, "queries": n} for t, n in sorted(tc.items(), key=lambda kv: (-kv[1], kv[0]))[:15] if n >= 2]

    return {
        "available": bool(events), "days": days, "slow_seconds": slow_s, "masked": mask,
        "coverage": {"days_with_data": len(fmt), "first": min(fmt) if fmt else None, "last": max(fmt) if fmt else None,
                     "jsonl_days": sum(1 for f in fmt.values() if f == "jsonl"), "text_days": sum(1 for f in fmt.values() if f == "text")},
        "totals": totals, "rates": rates,
        "latency_s": _stats([e.total_s for e in timed]), "tok_per_s": _stats([e.tok_per_s for e in user if e.tok_per_s])["p50"],
        "by_caller": dict(callers), "by_day": series, "top_queries": top_queries, "top_terms": top_terms,
    }


KINDS = ("slow", "no_result", "error")


def listing(config: ConsoleConfig, days: int, kind: str, limit: int, slow_seconds: float | None = None) -> dict:
    slow_s = config.slow_query_seconds if slow_seconds is None else slow_seconds
    events, _ = load(config, days)
    user = [e for e in events if not e.is_system]
    if kind == "slow":
        rows = sorted((e for e in user if e.total_s is not None and e.outcome in ("answered", "general_knowledge") and e.total_s >= slow_s),
                      key=lambda e: (-e.total_s, e.ts))
    elif kind == "no_result":
        rows = sorted((e for e in user if e.outcome == "no_relevant"), key=lambda e: e.ts, reverse=True)
    else:
        rows = sorted((e for e in user if e.outcome == "error"), key=lambda e: e.ts, reverse=True)
    mask = config.mask_queries
    return {"kind": kind, "days": days, "slow_seconds": slow_s, "total": len(rows), "masked": mask, "items": [
        {"ts": e.ts, "query": mask_text(e.query) if mask else e.query, "outcome": e.outcome, "caller": e.caller,
         "total_s": e.total_s, "n_sources": e.n_sources,
         "sources": [mask_path(s) if mask else s for s in e.sources[:5]],
         "error": mask_message(e.error) if mask else e.error} for e in rows[:limit]]}
