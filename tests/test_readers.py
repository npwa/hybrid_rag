from datetime import datetime

from console.readers import maintenance_log as ml
from console.readers import query_log as ql

OLD_FAIL_THEN_OK = """\
2026-09-25T21:58:22 === maintenance run start ===
2026-09-25T21:58:23 === maintenance run end: FAILED in 1s (no ingest result) ===
2026-09-25T22:01:10 === maintenance run start ===
2026-09-25T22:01:18 stage index: start (run_index.py --config config/index_config.yaml)
2026-09-25T22:01:25 stage index: ok (7s) stage=index elapsed=5.2 embedded_chunks=295
2026-09-25T22:01:25 === maintenance run end: OK in 19s (+20 ~5 -0) ===
"""


def test_last_run_decided_by_its_own_end_line_old_failure_then_ok():           # T-P1-2
    runs = ml.parse_runs(OLD_FAIL_THEN_OK)
    assert [r.result for r in runs] == ["FAILED", "OK"]
    last = ml.last_run(runs)
    assert last.result == "OK" and (last.added, last.changed, last.removed) == (20, 5, 0) and last.seconds == 19
    assert ml.last_successful_index(runs) == "2026-09-25T22:01:25"


def test_last_run_failed_after_ok_is_failed():
    text = OLD_FAIL_THEN_OK + "2026-09-26T21:58:22 === maintenance run start ===\n2026-09-26T21:58:24 === maintenance run end: FAILED in 2s (no ingest result) ===\n"
    runs = ml.parse_runs(text)
    assert ml.last_run(runs).result == "FAILED"
    assert ml.last_successful_index(runs) == "2026-09-25T22:01:25"     # last good index still known


def test_truncated_or_empty_log_is_tolerated(tmp_path):
    assert ml.read_runs(tmp_path / "missing.log") == []
    runs = ml.parse_runs("2026-10-01T01:00:00 === maintenance run start ===\n")
    assert runs[0].result is None and ml.last_successful_index(runs) is None


def test_hours_since():
    assert ml.hours_since("2026-10-30T00:00:00", datetime(2026, 10, 31, 12, 0, 0)) == 36.0
    assert ml.hours_since(None) is None


TEXT_LOG = """\
2026-10-30T09:57:42 INFO     QUERY 'home router external IP address' -> 8 sources, 14.19s [VPN.txt, Router/README]
2026-10-30T09:57:42 INFO     QUERY 'home router external IP address' fusion detail: VPN.txt branch=dense+sparse rrf=0.03279
2026-10-30T09:57:42 INFO     QUERY 'home router external IP address' generation: 24 tokens in 0.23s (104.4 tok/s)
2026-10-06T16:30:59 WARNING  QUERY_EMBED_FAILED 'stereo TV': could not reach Ollama at http://localhost:11434: timed out
2026-10-08T10:00:00 INFO     QUERY "what's the \\"x\\"?" -> not relevant, fallback disabled
2026-10-08T10:01:00 INFO     QUERY '### Task:\\nSuggest 3-5 relevant follow-up questions' -> 8 sources, 1.50s [a.txt]
2026-10-08T10:02:00 INFO     QUERY 'q' -> general-knowledge fallback, 2.25s
2026-10-08T10:03:00 WARNING  QUERY_GENERATION_FAILED 'q2': boom
"""


def test_text_log_parser_handles_all_real_line_shapes():
    ev = ql.parse_text_log(TEXT_LOG)
    assert [e.outcome for e in ev] == ["answered", "error", "no_relevant", "answered", "general_knowledge", "error"]
    a = ev[0]
    assert (a.query, a.total_s, a.n_sources, a.sources) == ("home router external IP address", 14.19, 8, ["VPN.txt", "Router/README"])
    assert (a.gen_tokens, a.tok_per_s) == (24, 104.4)
    assert ev[1].error.startswith("could not reach Ollama")
    assert ev[2].query == 'what\'s the "x"?'
    assert ev[3].is_system and not a.is_system             # Open WebUI follow-up prompt is flagged
    assert ev[4].total_s == 2.25 and ev[5].error == "boom"


def test_jsonl_and_text_agree_on_shared_fields(tmp_path):                    # basis for T-P3-2
    jl = '{"schema":1,"ts":"2026-10-30T09:57:42","query":"q","caller":"mcp","outcome":"answered","error":null,"n_sources":1,"sources":[{"rel_path":"a.txt"}],"total_s":2.5,"gen_tokens":10,"tok_per_s":5.0}\n{"torn'
    (tmp_path / "query_2026-10-30.jsonl").write_text(jl)
    (tmp_path / "query_2026-10-29.log").write_text("2026-10-29T01:00:00 INFO     QUERY 'q' -> 1 sources, 2.50s [a.txt]\n")
    j = ql.read_day(tmp_path, "2026-10-30")
    t = ql.read_day(tmp_path, "2026-10-29")
    assert len(j) == 1 and len(t) == 1                                         # torn last line ignored
    for f in ("query", "outcome", "total_s", "n_sources", "sources"):
        assert getattr(j[0], f) == getattr(t[0], f)
    assert j[0].caller == "mcp" and j[0].source_format == "jsonl" and t[0].caller is None
    assert ql.read_day(tmp_path, "2026-01-01") == []


def test_demo_query_logs_parse(demo_dir):
    total = 0
    for p in sorted((demo_dir / "logs").glob("query_*.log")):
        events = ql.parse_text_log(p.read_text())
        assert events                                                         # no line shape is silently dropped
        total += len(events)
    assert total > 20
