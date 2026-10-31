"""Readers for query logs: the human-readable text log (older days, FR-3.5 fallback) and the
JSONL sidecar (query/structured_log.py). Both produce the same QueryEvent."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_Q = r"(?P<q>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
_TS = r"(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)"
_ANSWERED = re.compile(rf"^{_TS} INFO\s+QUERY {_Q} -> (?P<n>\d+) sources, (?P<secs>[\d.]+)s \[(?P<src>.*)\]$")
_NOREL = re.compile(rf"^{_TS} INFO\s+QUERY {_Q} -> not relevant, fallback disabled$")
_GENERAL = re.compile(rf"^{_TS} INFO\s+QUERY {_Q} -> general-knowledge fallback, (?P<secs>[\d.]+)s$")
_EMBED_FAIL = re.compile(rf"^{_TS} WARNING\s+QUERY_EMBED_FAILED {_Q}: (?P<err>.*)$")
_GEN_FAIL = re.compile(rf"^{_TS} WARNING\s+QUERY_GENERATION_FAILED {_Q}: (?P<err>.*)$")
_GEN = re.compile(rf"^{_TS} INFO\s+QUERY {_Q} generation: (?P<tok>\d+) tokens in (?P<secs>[\d.]+)s \((?P<tps>[\d.]+) tok/s\)$")

SYSTEM_PREFIX = "### Task:"      # Open WebUI's automatic follow-up/title prompts


@dataclass
class QueryEvent:
    ts: str
    query: str
    outcome: str                    # answered | no_relevant | general_knowledge | error
    caller: str | None = None
    total_s: float | None = None
    n_sources: int = 0
    sources: list[str] = field(default_factory=list)
    error: str | None = None
    gen_tokens: int | None = None
    tok_per_s: float | None = None
    source_format: str = "text"

    @property
    def is_system(self) -> bool:
        return self.query.lstrip().startswith(SYSTEM_PREFIX)


def _unq(s: str) -> str:
    return ast.literal_eval(s)


def parse_text_log(text: str) -> list[QueryEvent]:
    events: list[QueryEvent] = []
    gen: dict[str, tuple[int, float]] = {}
    for line in text.splitlines():
        if m := _GEN.match(line):
            gen[_unq(m["q"])] = (int(m["tok"]), float(m["tps"]))
    for line in text.splitlines():
        if m := _ANSWERED.match(line):
            q = _unq(m["q"])
            ev = QueryEvent(m["ts"], q, "answered", total_s=float(m["secs"]), n_sources=int(m["n"]),
                            sources=[s.strip() for s in m["src"].split(", ")] if m["src"] else [])
            if q in gen:
                ev.gen_tokens, ev.tok_per_s = gen[q]
            events.append(ev)
        elif m := _NOREL.match(line):
            events.append(QueryEvent(m["ts"], _unq(m["q"]), "no_relevant"))
        elif m := _GENERAL.match(line):
            events.append(QueryEvent(m["ts"], _unq(m["q"]), "general_knowledge", total_s=float(m["secs"])))
        elif m := (_EMBED_FAIL.match(line) or _GEN_FAIL.match(line)):
            events.append(QueryEvent(m["ts"], _unq(m["q"]), "error", error=m["err"]))
    return events


def parse_jsonl(text: str) -> list[QueryEvent]:
    events = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue                  # a torn last line must not break the reader
        events.append(QueryEvent(
            ts=d["ts"], query=d["query"], outcome=d["outcome"], caller=d.get("caller"), total_s=d.get("total_s"),
            n_sources=d.get("n_sources", 0), sources=[s.get("rel_path", "") for s in d.get("sources", [])],
            error=d.get("error"), gen_tokens=d.get("gen_tokens"), tok_per_s=d.get("tok_per_s"), source_format="jsonl"))
    return events


def read_day(logs_dir: Path, day: str) -> list[QueryEvent]:
    """Events for one day (YYYY-MM-DD). The JSONL log is richer (caller, timings) but starts whenever the engine that
    writes it was last started, so a day can have a JSONL file that covers only its end. Text-log events from before the
    first JSONL record are added, so such a day is not cut short; from then on the JSONL is the single source."""
    j, t = Path(logs_dir) / f"query_{day}.jsonl", Path(logs_dir) / f"query_{day}.log"
    text_events = parse_text_log(t.read_text(encoding="utf-8", errors="replace")) if t.exists() else []
    if not j.exists():
        return text_events
    json_events = parse_jsonl(j.read_text(encoding="utf-8", errors="replace"))
    if not json_events:
        return text_events
    first = min(e.ts for e in json_events)
    return [e for e in text_events if e.ts < first] + json_events
