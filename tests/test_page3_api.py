"""Page 3 (query analytics): T-P3-1 aggregates against independently computed values, T-P3-2 parser agreement,
T-P3-3 configurable slow threshold / recurring terms, T-PRIV-2 masking."""
import dataclasses
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console.api import create_app
from console.readers import query_log

RECORDS = {   # day -> [(time, query, outcome, total_s, n_sources, caller, tok_per_s)]
    "2026-10-28": [("08:00:00", "what is the guest wifi password", "answered", 2.0, 8, "mcp", 50.0),
                   ("09:00:00", "what is the guest wifi password", "answered", 4.0, 8, "cli", 70.0),
                   ("10:00:00", "### Task: suggest follow-up questions", "answered", 1.0, 8, "http", None)],
    "2026-10-29": [("08:00:00", "when is the furnace service due", "answered", 31.0, 8, "mcp", None),
                   ("09:00:00", "unknown gizmo specification", "no_relevant", 0.1, 0, "mcp", None),
                   ("10:00:00", "what is the guest wifi password", "error", 60.0, 0, "http", None)],
    "2026-10-30": [("08:00:00", "furnace filter size", "answered", 10.0, 8, "mcp", None),
                   ("09:00:00", "furnace filter size", "general_knowledge", 12.0, 0, "http", None),
                   ("10:00:00", "unknown gizmo specification", "no_relevant", 0.2, 0, "mcp", None),
                   ("11:00:00", "unknown gizmo specification", "answered", 80.0, 8, "mcp", None)],
}


def write_logs(logs: Path, records=RECORDS):
    logs.mkdir(parents=True, exist_ok=True)
    for day, rows in records.items():
        lines = [json.dumps({"schema": 1, "ts": f"{day}T{t}", "query": q, "caller": c, "outcome": o, "error": "boom /secret/path.txt" if o == "error" else None,
                             "n_sources": n, "sources": [{"rel_path": f"Private/Folder/doc{i}.pdf"} for i in range(n)], "total_s": s,
                             "tok_per_s": tps}) for t, q, o, s, n, c, tps in rows]
        (logs / f"query_{day}.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture()
def month(demo_config, tmp_path):
    cfg = dataclasses.replace(demo_config, logs_dir=tmp_path / "logs")
    write_logs(cfg.logs_dir)
    return cfg


def get(cfg, url):
    r = TestClient(create_app(cfg)).get(url)
    assert r.status_code == 200, r.text
    return r.json()


def test_aggregates_equal_hand_computed_values(month):                                           # T-P3-1
    d = get(month, "/api/v1/queries/stats?days=30")
    t = d["totals"]
    assert t["queries"] == 9 and t["system_queries"] == 1                       # the "### Task:" prompt is not a user query
    assert t["by_outcome"] == {"answered": 5, "no_relevant": 2, "general_knowledge": 1, "error": 1}
    assert t["zero_sources"] == 4 and t["timed"] == 6 and t["slow"] == 2        # slow: 31.0 and 80.0 (>= 30)
    assert d["rates"] == {"no_relevant": 22.2, "general_knowledge": 11.1, "error": 11.1, "zero_sources": 44.4, "slow": 33.3}
    # latency covers answered + general knowledge only: 2, 4, 10, 12, 31, 80
    assert d["latency_s"]["count"] == 6 and d["latency_s"]["p95"] == 80.0 and d["latency_s"]["max"] == 80.0
    assert d["latency_s"]["p50"] in (10.0, 12.0)            # the two middle values (nearest rank picks one of them)
    assert d["tok_per_s"] in (50.0, 70.0)                   # median of the two recorded rates
    assert d["by_caller"] == {"mcp": 6, "cli": 1, "http": 2}
    days = {r["day"]: r for r in d["by_day"]}
    assert [days[k]["queries"] for k in sorted(days)] == [2, 3, 4]
    assert days["2026-10-30"]["no_relevant"] == 1 and days["2026-10-30"]["slow"] == 1 and days["2026-10-29"]["error"] == 1
    assert d["coverage"] == {"days_with_data": 3, "first": "2026-10-28", "last": "2026-10-30", "jsonl_days": 3, "text_days": 0}


def test_demo_aggregates_match_an_independent_count(demo_config):                                # T-P3-1 (generated month)
    d = get(demo_config, "/api/v1/queries/stats?days=30")
    rows = [json.loads(l) for f in sorted(demo_config.logs_dir.glob("query_*.jsonl")) for l in f.read_text().splitlines()]
    assert d["totals"]["queries"] == len(rows)
    for outcome in ("answered", "no_relevant", "error"):
        assert d["totals"]["by_outcome"][outcome] == sum(1 for r in rows if r["outcome"] == outcome)
    secs = sorted(r["total_s"] for r in rows if r["outcome"] in ("answered", "general_knowledge"))
    assert d["latency_s"]["max"] == secs[-1] and d["latency_s"]["count"] == len(secs)
    assert secs[0] <= d["latency_s"]["p50"] <= d["latency_s"]["p95"] <= secs[-1]
    assert abs(d["latency_s"]["p50"] - secs[len(secs) // 2]) <= 6.0     # nearest rank vs. the middle value
    assert sum(r["queries"] for r in d["by_day"]) == len(rows) and d["by_caller"] == {c: sum(1 for r in rows if r["caller"] == c) for c in {r["caller"] for r in rows}}


def test_text_and_jsonl_parsers_agree_on_days_with_both(demo_config):                           # T-P3-2
    for jf in sorted(demo_config.logs_dir.glob("query_*.jsonl")):
        tf = jf.with_suffix(".log")
        a = query_log.parse_jsonl(jf.read_text())
        b = query_log.parse_text_log(tf.read_text()) if tf.exists() else []
        assert [(e.ts, e.query, e.outcome) for e in a if e.outcome != "no_relevant" or True] == [(e.ts, e.query, e.outcome) for e in b], jf.name
        assert [(e.n_sources, e.total_s) for e in a if e.outcome == "answered"] == [(e.n_sources, e.total_s) for e in b if e.outcome == "answered"]


def test_partial_jsonl_day_keeps_earlier_text_events(tmp_path):                                  # the engine was restarted mid-day
    (tmp_path / "query_2026-10-30.log").write_text(
        "2026-10-30T08:00:00 INFO     QUERY 'early question' -> 3 sources, 2.0s [a, b, c]\n"
        "2026-10-30T23:55:10 INFO     QUERY 'late question' -> 3 sources, 3.0s [a, b, c]\n")
    (tmp_path / "query_2026-10-30.jsonl").write_text(json.dumps(
        {"ts": "2026-10-30T23:55:10", "query": "late question", "caller": "mcp", "outcome": "answered", "n_sources": 3,
         "sources": [], "total_s": 3.0}) + "\n")
    evs = query_log.read_day(tmp_path, "2026-10-30")
    assert [(e.query, e.source_format) for e in evs] == [("early question", "text"), ("late question", "jsonl")]


def test_slow_threshold_is_configurable(month):                                                  # T-P3-3
    assert get(month, "/api/v1/queries/stats")["totals"]["slow"] == 2
    d = get(month, "/api/v1/queries/stats?slow_seconds=11")
    assert d["totals"]["slow"] == 3 and d["slow_seconds"] == 11
    slow = get(month, "/api/v1/queries/slow?kind=slow")
    assert [r["total_s"] for r in slow["items"]] == [80.0, 31.0] and slow["total"] == 2
    assert get(month, "/api/v1/queries/slow?kind=slow&slow_seconds=100")["items"] == []


def test_recurring_questions_and_terms(month):                                                   # T-P3-3
    d = get(month, "/api/v1/queries/stats")
    top = {q["query"]: q for q in d["top_queries"]}
    assert top["what is the guest wifi password"]["count"] == 3 and top["unknown gizmo specification"]["count"] == 3
    assert top["unknown gizmo specification"]["no_relevant"] == 2 and "suggest follow-up questions" not in " ".join(top)
    terms = {t["term"]: t["queries"] for t in d["top_terms"]}
    assert terms["wifi"] == 3 and terms["furnace"] == 3 and terms["gizmo"] == 3 and "what" not in terms and "the" not in terms


def test_no_result_and_error_lists(month):
    nr = get(month, "/api/v1/queries/slow?kind=no_result")
    assert nr["total"] == 2 and [r["ts"] for r in nr["items"]] == ["2026-10-30T10:00:00", "2026-10-29T09:00:00"]
    er = get(month, "/api/v1/queries/slow?kind=error")
    assert er["total"] == 1 and er["items"][0]["error"].startswith("boom")
    assert len(get(month, "/api/v1/queries/slow?kind=no_result&limit=1")["items"]) == 1


def test_window_and_validation(month):
    assert get(month, "/api/v1/queries/stats?days=3")["totals"]["queries"] == 7          # 29, 30 and (empty) 31 Oct
    assert get(month, "/api/v1/queries/stats?days=2")["totals"]["queries"] == 4
    c = TestClient(create_app(month))
    for bad in ("days=0", "days=999", "slow_seconds=0", "kind=nope"):
        assert c.get(f"/api/v1/queries/{'slow' if 'kind' in bad else 'stats'}?{bad}").status_code == 422


def test_empty_logs_directory(demo_config, tmp_path):
    d = get(dataclasses.replace(demo_config, logs_dir=tmp_path / "none"), "/api/v1/queries/stats")
    assert d["available"] is False and d["totals"]["queries"] == 0 and d["rates"]["slow"] is None and d["by_day"] == []


def test_masking_hides_query_text_and_paths(month):                                              # T-PRIV-2
    cfg = dataclasses.replace(month, mask_queries=True)
    bodies = [json.dumps(get(cfg, u)) for u in ("/api/v1/queries/stats", "/api/v1/queries/slow?kind=slow", "/api/v1/queries/slow?kind=no_result",
                                                 "/api/v1/queries/slow?kind=error")]
    for body in bodies:
        for secret in ("wifi", "furnace", "gizmo", "Private/Folder", "doc0", "secret/path"):
            assert secret not in body, secret
    stats = json.loads(bodies[0])
    assert stats["masked"] is True and stats["top_terms"] == [] and stats["top_queries"][0]["query"].startswith("[masked-")
    assert stats["top_queries"][0]["count"] == 3             # recurrence still countable
    assert json.loads(bodies[1])["items"][0]["sources"][0].startswith("[masked-")
