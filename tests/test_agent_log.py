"""Page 4 parser and analysis: T-P4-1 (real sample logs), T-P4-3 (failure case), T-P4-4 (model change), T-P4-5 (time to tool)."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from console.readers import agent_log as al
from console.readers.query_log import QueryEvent

FIX = Path(__file__).parent / "fixtures" / "agent"


def rec(sub, msg, when, level="INFO"):
    return json.dumps({"0": json.dumps({"subsystem": sub}), "1": msg, "_meta": {"logLevelName": level},
                       "time": when.strftime("%Y-%m-%dT%H:%M:%S.000-07:00")})


def start(run, when, ms=5000):
    return rec("auto-reply/agent-turn-timing", {"runId": run, "sessionKey": "agent:main:main", "milestone": "tool_execution_started", "totalMs": ms}, when)


def kinds(events):
    out = {}
    for e in events:
        out[e.kind] = out.get(e.kind, 0) + 1
    return out


def test_real_sample_logs_parse_and_unknown_records_are_ignored():                 # T-P4-1
    events, files = al.read_dir(FIX)
    assert [f.name for f in files] == ["openclaw-2026-09-05.log", "openclaw-2026-10-29.log", "openclaw-2026-10-30.log"]
    k = kinds(events)
    assert k["tool_started"] == 1 and k["model_set"] == 3 and k["gateway_ready"] == 3
    assert k["host_gap"] == 1 and k["provider_preflight"] == 1 and k["agent_failed"] == 1 and k["memory_sync_failed"] == 4
    ts = next(e for e in events if e.kind == "tool_started")
    assert ts.value == 50248 and ts.run_id and ts.session_key == "agent:main:main" and ts.ts == datetime(2026, 10, 30, 9, 57, 28, 438000)
    gap = next(e for e in events if e.kind == "host_gap")
    assert gap.value == 32123198


def test_models_are_attributed_by_the_last_model_line_and_fallback_is_used_before_any():           # T-P4-4
    events, _ = al.read_dir(FIX)
    al.attribute_models(events, fallback="ollama/fallback")
    by_day = {}
    for e in events:
        if e.kind in ("host_gap", "tool_started", "agent_failed"):
            by_day[(e.ts.date().isoformat(), e.kind)] = e.model
    assert by_day[("2026-09-05", "agent_failed")] == "ollama/qwen2.5:14b-instruct"        # Sept: the small model was configured
    assert by_day[("2026-10-30", "tool_started")] == "ollama/qwen3.6:35b-a3b"


def test_model_change_mid_day_splits_turns_between_models():
    t = datetime(2026, 10, 30, 8, 0, 0)
    lines = [rec("gateway", "agent model: ollama/small (thinking=low)", t),
             start("r1", t + timedelta(minutes=5)), start("r2", t + timedelta(minutes=10)),
             rec("gateway", "agent model: ollama/big (thinking=low)", t + timedelta(minutes=20)),
             start("r3", t + timedelta(minutes=30))]
    ev = al.parse_lines(lines)
    r = al.analyze(ev, [], days=3650, now=t + timedelta(hours=2))
    models = {m["model"]: m for m in r["models"]}
    assert models["ollama/small"]["turns"] == 2 and models["ollama/big"]["turns"] == 1
    assert r["by_day"][0]["models"] == ["ollama/big", "ollama/small"]


def test_looks_like_tool_call_detected_in_any_shape():                                 # T-P4-3 (documented text)
    t = datetime(2026, 10, 30, 9, 0, 0)
    ev = al.parse_lines([
        rec("agent/embedded", al.LOOKS_LIKE, t, "WARN"),
        rec("agent/embedded", {"runId": "r9", "message": al.LOOKS_LIKE}, t + timedelta(minutes=1), "WARN"),
        rec("x", "Assistant reply looks like a tool call, but no structured tool invocation was emitted (model=m)", t + timedelta(minutes=2)),
        rec("agent/embedded", "something else", t + timedelta(minutes=3))])
    assert [e.kind for e in ev] == ["looks_like_tool_call"] * 3
    r = al.analyze(ev, [], days=3650, now=t + timedelta(hours=1))
    assert r["totals"]["looks_like_tool_call"] == 3 and any(f["kind"] == "looks_like_tool_call" for f in r["flags"])


def test_turn_without_tool_start_is_counted_as_a_turn_without_a_tool_call():     # fallback signal until the real message is seen
    t = datetime(2026, 10, 30, 9, 0, 0)
    ev = al.parse_lines([start("a", t), rec("auto-reply/agent-turn-timing", {"runId": "b", "milestone": "model_response_received", "totalMs": 9000}, t + timedelta(minutes=5))])
    r = al.analyze(ev, [], days=3650, now=t + timedelta(hours=1))
    assert r["totals"]["turns"] == 2 and r["totals"]["tool_starts"] == 1
    assert r["models"][0]["tool_rate"] == 0.5


def test_time_to_tool_percentiles_include_the_real_record():                       # T-P4-5
    t = datetime(2026, 10, 30, 9, 0, 0)
    vals = [3200, 5400, 9800, 21000, 50248]
    ev = al.parse_lines([start(f"r{i}", t + timedelta(minutes=i), v) for i, v in enumerate(vals)])
    r = al.analyze(ev, [], days=3650, now=t + timedelta(hours=1))
    s = r["time_to_tool_ms"]
    assert s["count"] == 5 and s["p50"] == 9800 and s["max"] == 50248 and s["p95"] == 50248
    assert [x["ms"] for x in r["time_to_tool_samples"]] == vals


def test_matching_pairs_agent_starts_with_desktop_requests():                      # T-P4-2 (algorithm)
    t = datetime(2026, 10, 30, 9, 0, 0)
    starts = al.parse_lines([start("a", t), start("b", t + timedelta(minutes=10)), start("c", t + timedelta(minutes=20))])
    calls = [al.McpCall(t + timedelta(seconds=2), "mcp", "answered", 5.0),                         # matches a
             al.McpCall(t + timedelta(minutes=10, seconds=-3), "mcp", "answered", 5.0),            # matches b
             al.McpCall(t + timedelta(minutes=40), "mcp", "answered", 1.0)]                        # no agent start
    pairs, lone, desk = al.match(starts, calls)
    assert [p[0].run_id for p in pairs] == ["a", "b"] and [s.run_id for s in lone] == ["c"] and len(desk) == 1
    # one desktop call can pair only once
    p2, l2, d2 = al.match(al.parse_lines([start("x", t), start("y", t + timedelta(seconds=5))]), [al.McpCall(t, "mcp", "answered", 1)])
    assert len(p2) == 1 and len(l2) == 1 and d2 == []


def test_mcp_calls_use_mcp_caller_and_keep_callerless_text_days_as_uncertain():
    q = [QueryEvent("2026-10-30T09:57:42", "q", "answered", caller="mcp", total_s=14.19),
         QueryEvent("2026-10-30T09:58:00", "q", "answered", caller="cli", total_s=1.0),
         QueryEvent("2026-10-30T09:59:00", "q", "answered", caller=None, total_s=1.0)]
    calls = al.mcp_calls_from_events(q)
    assert [(c.caller, c.certain) for c in calls] == [("mcp", True), ("unknown", False)]       # the cli call is dropped
    assert calls[0].start == datetime(2026, 10, 30, 9, 57, 27, 810000)
    real_start = al.parse_lines([start("a", datetime(2026, 10, 30, 9, 57, 28, 438000), 50248)])
    assert len(al.match(real_start, calls)[0]) == 1               # the real 2026-10-30 pair reconciles


def test_text_only_day_confirms_a_start_but_is_not_counted_as_an_mcp_request():
    t = datetime(2026, 10, 30, 9, 57, 28)
    ev = al.parse_lines([start("a", t, 50248)])
    text_only = [QueryEvent("2026-10-30T09:57:42", "q", "answered", caller=None, total_s=14.19),
                 QueryEvent("2026-10-30T12:00:00", "other", "answered", caller=None, total_s=2.0)]        # maybe a CLI query
    r = al.analyze(ev, al.mcp_calls_from_events(text_only), days=3650, now=t + timedelta(hours=1))
    assert r["totals"]["matched"] == 1 and r["totals"]["matched_by_time_only"] == 1
    assert r["totals"]["agent_starts_without_desktop_call"] == 0
    assert r["totals"]["desktop_calls_without_agent_start"] == 0 and r["desktop"]["calls"] == 0     # never reported as MCP traffic
    assert r["by_day"][0]["desktop_mcp_calls"] == 0 and r["by_day"][0]["matched"] == 1


def test_connect_failure_and_policy_removal_become_flags_with_context():
    t = datetime(2026, 10, 30, 7, 0, 0)
    ev = al.parse_lines([
        rec("agent/embedded", 'MCP: failed to start server "hybrid-rag": connect ECONNREFUSED', t, "ERROR"),
        rec("auto-reply/agent-turn-timing", {"runId": "q1", "milestone": "model_response_received", "totalMs": 100}, t + timedelta(minutes=5)),
        rec("auto-reply/agent-turn-timing", {"runId": "q2", "milestone": "model_response_received", "totalMs": 100}, t + timedelta(minutes=6)),
        start("q3", t + timedelta(minutes=30)),
        rec("agents/tool-policy", {"rule": "tools.allow", "removedTools": ["other", al.TOOL]}, t + timedelta(minutes=31)),
        rec("agents/tool-policy", {"rule": "tools.allow", "removedTools": ["only_other"]}, t + timedelta(minutes=32))])
    r = al.analyze(ev, [], days=3650, now=t + timedelta(hours=3))
    kinds_ = {f["kind"]: f for f in r["flags"]}
    assert kinds_["mcp_connect_failure"]["turns_without_tool_after"] == 2
    assert kinds_["tool_removed_by_policy"]["detail"] == "removed by rule: tools.allow"
    assert r["totals"]["tool_removed_by_policy"] == 1 and r["totals"]["mcp_connect_failures"] == 1


def test_robust_to_garbage_and_missing_times(tmp_path):
    lines = ["", "not json", "[1,2]", json.dumps({"1": "no time at all"}), json.dumps({"time": "garbage", "1": "x"}),
             json.dumps({"_meta": {"date": "2026-10-30T16:57:28.000Z"}, "0": "{\"subsystem\":\"gateway\"}", "1": "gateway ready"})]
    ev = al.parse_lines(lines)
    assert [e.kind for e in ev] == ["gateway_ready"]                          # UTC meta date converted to local wall time
    assert al.read_dir(tmp_path / "nope") == ([], [])
    r = al.analyze([], [], days=7)
    assert r["totals"]["turns"] == 0 and r["models"] == [] and r["time_to_tool_ms"]["p50"] is None


def test_dev_instance_logs_are_ignored(tmp_path):
    (tmp_path / "openclaw-2026-10-30.log").write_text(start("a", datetime(2026, 10, 30, 9, 0, 0)) + "\n")
    (tmp_path / "openclaw-dev-2026-10-30.log").write_text(start("dev", datetime(2026, 10, 30, 9, 0, 0)) + "\n")
    ev, files = al.read_dir(tmp_path)
    assert [f.name for f in files] == ["openclaw-2026-10-30.log"] and [e.run_id for e in ev] == ["a"]
