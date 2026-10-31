"""OpenClaw agent logs (JSON lines, one per line) -> events and the Page 4 analysis.

Source: local copies in logs/agent/ made by scripts/pull_agent_logs.sh from /tmp/openclaw on the bot VM. Record shapes
are taken from real logs (2026-09-05, 10-29, 10-30); unknown records are ignored, never an error.

What is recognised (kind -> how):
  tool_started        subsystem auto-reply/agent-turn-timing, milestone tool_execution_started (runId, sessionKey, totalMs)
  turn_seen           any other agent-turn-timing record (a turn that reached some milestone)
  looks_like_tool_call  text 'looks like a tool call, but no structured tool invocation was emitted' (documented in
                      Doc/step-5-requirements.md; NOT yet seen in a real log, see step-9 requirements open question 9)
  mcp_connect_failure text 'failed to start server "hybrid-rag"'
  tool_removed        agents/tool-policy record whose removedTools contains the RAG tool
  model_set           gateway 'agent model: <model> (...)'
  gateway_ready       gateway 'gateway ready'
  host_gap            'host timing gap detected: process was frozen ~N ms'
  provider_preflight  cron preflight to the local provider (Ollama) failed
  agent_failed        'Embedded agent failed before reply'
  memory_sync_failed  OpenClaw's own memory feature failed (unrelated to this project's index)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

TOOL = "hybrid-rag__ask_documents"
LOOKS_LIKE = "looks like a tool call, but no structured tool invocation was emitted"
MATCH_WINDOW_S = 20.0           # agent tool start vs desktop request start (embedding begins right after the tool call)
UNKNOWN_MODEL = "unknown"

_MODEL = re.compile(r"agent model: (\S+)")
_FROZEN = re.compile(r"frozen ~(\d+)ms")


@dataclass
class AgentEvent:
    ts: datetime
    kind: str
    model: str = UNKNOWN_MODEL
    run_id: str | None = None
    session_key: str | None = None
    value: float | None = None          # totalMs for tool_started, ms frozen for host_gap
    detail: str = ""
    source: str = ""


def _subsystem(d: dict) -> str:
    raw = d.get("0")
    if isinstance(raw, str):
        try:
            j = json.loads(raw)
            if isinstance(j, dict):
                return str(j.get("subsystem") or j.get("module") or raw)
        except json.JSONDecodeError:
            pass
        return raw
    return ""


def _when(d: dict) -> datetime | None:
    t = d.get("time")
    try:
        if t:
            return datetime.fromisoformat(t).replace(tzinfo=None)        # local wall time, same zone as the desktop
        meta = (d.get("_meta") or {}).get("date")
        if meta:
            return datetime.fromisoformat(meta.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None
    return None


def _text(d: dict) -> str:
    m = d.get("1", d.get("message", ""))
    return m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)


def parse_lines(lines, source: str = "") -> list[AgentEvent]:
    events: list[AgentEvent] = []
    for line in lines:
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        ts, sub, text = _when(d), _subsystem(d), _text(d)
        if ts is None:
            continue
        obj = d.get("1") if isinstance(d.get("1"), dict) else {}

        def add(kind, **kw):
            events.append(AgentEvent(ts=ts, kind=kind, source=source, **kw))

        if sub == "auto-reply/agent-turn-timing" and obj.get("milestone"):
            kw = dict(run_id=obj.get("runId"), session_key=obj.get("sessionKey"))
            if obj["milestone"] == "tool_execution_started":
                add("tool_started", value=float(obj.get("totalMs") or 0), **kw)
            else:
                add("turn_seen", detail=str(obj["milestone"]), value=float(obj.get("totalMs") or 0), **kw)
        if LOOKS_LIKE in text:
            add("looks_like_tool_call", run_id=obj.get("runId"), session_key=obj.get("sessionKey"), detail=text[:200])
        if 'failed to start server "hybrid-rag"' in text or "failed to start server \\\"hybrid-rag\\\"" in text:
            add("mcp_connect_failure", detail=text[:200])
        if sub == "agents/tool-policy" and TOOL in (obj.get("removedTools") or []):
            add("tool_removed", detail=f"removed by rule: {obj.get('rule')}")
        if sub == "gateway" and (m := _MODEL.search(text)):
            add("model_set", detail=m.group(1))
        if sub == "gateway" and text.strip() == "gateway ready":
            add("gateway_ready")
        if "host timing gap detected" in text and (m := _FROZEN.search(text)):
            add("host_gap", value=float(m.group(1)), detail=text[:160])
        if "provider preflight failed" in text:
            add("provider_preflight", detail=text[:240])
        if text.startswith("Embedded agent failed before reply"):
            add("agent_failed", detail=text[:200])
        if sub == "memory" and "memory sync failed" in text:
            add("memory_sync_failed", detail=text[:160])
    return events


def read_dir(agent_logs_dir: Path) -> tuple[list[AgentEvent], list[Path]]:
    """All openclaw-*.log copies (not the dev instance's), oldest first; events sorted by time with models attributed."""
    files = sorted(p for p in Path(agent_logs_dir).glob("openclaw-*.log") if not p.name.startswith("openclaw-dev-")) \
        if Path(agent_logs_dir).is_dir() else []
    events: list[AgentEvent] = []
    for p in files:
        events += parse_lines(p.read_text(encoding="utf-8", errors="replace").splitlines(), p.name)
    events.sort(key=lambda e: e.ts)
    return events, files


def attribute_models(events: list[AgentEvent], fallback: str | None = None) -> None:
    """Each event gets the model in effect when it happened: the last `agent model:` line before it."""
    current = fallback or UNKNOWN_MODEL
    for e in events:
        if e.kind == "model_set":
            current = e.detail
        e.model = current


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(q * len(s) + 0.5)) - 1))]


def _stats(values: list[float]) -> dict:
    return {"count": len(values), "p50": _pct(values, 0.5), "p95": _pct(values, 0.95), "max": max(values) if values else None}


@dataclass
class McpCall:
    start: datetime               # when the desktop began the request (record time minus its duration)
    caller: str | None
    outcome: str
    total_s: float | None
    certain: bool = True          # False: from a text-only day (no caller recorded): used to confirm a tool start, never counted as an MCP request


def mcp_calls_from_events(query_events) -> list[McpCall]:
    """MCP requests as the desktop saw them. JSONL records name the caller, so only caller=mcp counts. Days that have
    only the text log carry no caller; those queries are kept as uncertain calls so an agent tool start from before the
    structured log existed can still be matched (and is not reported as "never arrived")."""
    out = []
    for q in query_events:
        if q.caller not in ("mcp", None):
            continue
        end = datetime.fromisoformat(q.ts)
        out.append(McpCall(end - timedelta(seconds=q.total_s or 0.0), q.caller or "unknown", q.outcome, q.total_s,
                           certain=q.caller == "mcp"))
    return out


def match(starts: list[AgentEvent], calls: list[McpCall], window_s: float = MATCH_WINDOW_S):
    """Greedy pairing by time. Returns (pairs, unmatched_agent_starts, unmatched_desktop_calls)."""
    unused = list(range(len(calls)))
    pairs, lone = [], []
    for s in starts:
        best, bd = None, window_s + 1
        for i in unused:
            d = abs((calls[i].start - s.ts).total_seconds())
            if d < bd:
                best, bd = i, d
        if best is not None and bd <= window_s:
            pairs.append((s, calls[best]))
            unused.remove(best)
        else:
            lone.append(s)
    return pairs, lone, [calls[i] for i in unused]


def analyze(events: list[AgentEvent], calls: list[McpCall], *, days: int = 30, now: datetime | None = None,
            fallback_model: str | None = None) -> dict:
    now = now or datetime.now()
    since = now - timedelta(days=days)
    attribute_models(events, fallback_model)
    ev = [e for e in events if e.ts >= since]
    calls = [c for c in calls if c.start >= since]
    starts = [e for e in ev if e.kind == "tool_started"]
    pairs, lone, desk_lone = match(starts, calls)
    desk_lone = [c for c in desk_lone if c.certain]
    certain_calls = [c for c in calls if c.certain]

    runs: dict[str, dict] = {}
    for e in ev:
        if e.kind in ("tool_started", "turn_seen") and e.run_id:
            r = runs.setdefault(e.run_id, {"model": e.model, "ts": e.ts, "tool": False})
            r["tool"] = r["tool"] or e.kind == "tool_started"
    models: dict[str, dict] = {}
    for rid, r in runs.items():
        m = models.setdefault(r["model"], {"model": r["model"], "turns": 0, "tool_starts": 0, "ttt": [], "looks_like": 0})
        m["turns"] += 1
        m["tool_starts"] += int(r["tool"])
    for e in ev:
        if e.kind == "tool_started":
            models.setdefault(e.model, {"model": e.model, "turns": 0, "tool_starts": 0, "ttt": [], "looks_like": 0})["ttt"].append(e.value or 0)
        elif e.kind == "looks_like_tool_call":
            models.setdefault(e.model, {"model": e.model, "turns": 0, "tool_starts": 0, "ttt": [], "looks_like": 0})["looks_like"] += 1
    model_rows = []
    for m in models.values():
        t = _stats(m.pop("ttt"))
        model_rows.append({**m, "tool_rate": round(m["tool_starts"] / m["turns"], 3) if m["turns"] else None,
                           "time_to_tool_ms": t})
    model_rows.sort(key=lambda r: -r["turns"])

    by_day: dict[str, dict] = {}

    def day(ts: datetime) -> dict:
        return by_day.setdefault(ts.date().isoformat(), {
            "day": ts.date().isoformat(), "turns": 0, "tool_starts": 0, "looks_like_tool_call": 0, "ttt": [],
            "desktop_mcp_calls": 0, "matched": 0, "agent_starts_without_desktop_call": 0, "mcp_connect_failures": 0,
            "host_gaps": 0, "models": set()})
    for r in runs.values():
        d = day(r["ts"]); d["turns"] += 1; d["tool_starts"] += int(r["tool"]); d["models"].add(r["model"])
    for e in ev:
        if e.kind == "tool_started": day(e.ts)["ttt"].append(e.value or 0)
        elif e.kind == "looks_like_tool_call": day(e.ts)["looks_like_tool_call"] += 1
        elif e.kind == "mcp_connect_failure": day(e.ts)["mcp_connect_failures"] += 1
        elif e.kind == "host_gap": day(e.ts)["host_gaps"] += 1
    for c in certain_calls: day(c.start)["desktop_mcp_calls"] += 1
    for s, _ in pairs: day(s.ts)["matched"] += 1
    for s in lone: day(s.ts)["agent_starts_without_desktop_call"] += 1
    day_rows = []
    for d in sorted(by_day.values(), key=lambda x: x["day"]):
        t = _stats(d.pop("ttt")); d["time_to_tool_ms"] = t; d["models"] = sorted(d["models"]); day_rows.append(d)

    # Flags (FR-4.4): things an operator should look at
    flags = []
    removed_seen = False
    for e in ev:
        if e.kind == "mcp_connect_failure":
            nxt = [x for x in ev if x.ts > e.ts and x.kind == "tool_started"]
            turns_between = {x.run_id for x in ev if x.ts > e.ts and x.kind == "turn_seen" and (not nxt or x.ts < nxt[0].ts)}
            flags.append({"kind": "mcp_connect_failure", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model,
                          "detail": "OpenClaw could not connect to the hybrid-rag MCP server; sessions started now have no tool until /new",
                          "turns_without_tool_after": len(turns_between)})
        elif e.kind == "tool_removed":
            removed_seen = True
            flags.append({"kind": "tool_removed_by_policy", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model, "detail": e.detail})
        elif e.kind == "looks_like_tool_call":
            flags.append({"kind": "looks_like_tool_call", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model,
                          "detail": "the model wrote a tool call as text instead of calling the tool"})
        elif e.kind == "host_gap":
            flags.append({"kind": "host_gap", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model,
                          "detail": f"the VM was frozen for about {round((e.value or 0) / 3600000, 1)} h"})
        elif e.kind == "provider_preflight":
            flags.append({"kind": "provider_preflight_failed", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model, "detail": e.detail})
        elif e.kind == "agent_failed":
            flags.append({"kind": "agent_failed", "ts": e.ts.isoformat(timespec="seconds"), "model": e.model, "detail": e.detail})
    for s in lone:
        flags.append({"kind": "tool_start_without_desktop_call", "ts": s.ts.isoformat(timespec="seconds"), "model": s.model,
                      "detail": "the agent started the tool but the desktop logged no matching request (MCP server down or unreachable?)"})
    flags.sort(key=lambda f: f["ts"], reverse=True)

    ttt_all = [e.value or 0 for e in starts]
    desk = [c.total_s for c in certain_calls if c.total_s is not None]
    outcomes: dict[str, int] = {}
    for c in certain_calls:
        outcomes[c.outcome] = outcomes.get(c.outcome, 0) + 1
    return {
        "days": days,
        "coverage": {"first": min((e.ts for e in events), default=None) and min(e.ts for e in events).isoformat(timespec="seconds"),
                     "last": max((e.ts for e in events), default=None) and max(e.ts for e in events).isoformat(timespec="seconds")},
        "totals": {"turns": len(runs), "tool_starts": len(starts), "matched": len(pairs), "matched_by_time_only": sum(1 for _, c in pairs if not c.certain),
                   "agent_starts_without_desktop_call": len(lone), "desktop_calls_without_agent_start": len(desk_lone),
                   "looks_like_tool_call": sum(1 for e in ev if e.kind == "looks_like_tool_call"),
                   "mcp_connect_failures": sum(1 for e in ev if e.kind == "mcp_connect_failure"),
                   "tool_removed_by_policy": int(removed_seen)},
        "models": model_rows,
        "by_day": day_rows,
        "time_to_tool_ms": _stats(ttt_all),
        "time_to_tool_samples": [{"ts": e.ts.isoformat(timespec="seconds"), "ms": e.value, "model": e.model} for e in starts[-200:]],
        "desktop": {"calls": len(certain_calls), "total_s": _stats(desk), "by_outcome": outcomes},
        "flags": flags[:100],
    }
