"""T-LOG-1 / T-LOG-2: the structured JSONL log has the agreed fields for every caller and
outcome, and the human-readable text log is unchanged by adding it.

The GOLDEN_TEXT lines were captured from the engine *before* the JSONL change, using the same
stubs (tests/engine_harness.py)."""
import json
import logging
import re
from datetime import date

import pytest

from query.structured_log import OUTCOMES
from tests.engine_harness import make_config, run

Q = "what is x"
GOLDEN_TEXT = {
    "answered": [
        "QUERY 'what is x' -> 8 sources, Ns [Docs/file0.txt, Docs/file1.txt, Docs/file2.txt, Docs/file9.txt, Docs/file3.txt, Docs/file4.txt, Docs/file5.txt, Docs/file6.txt]",
        "QUERY 'what is x' fusion detail: Docs/file0.txt branch=dense+sparse rrf=0.03252 dense(rank=1,dist=0.5) sparse(rank=2,bm25=-20.0); Docs/file1.txt branch=dense+sparse rrf=0.03252 dense(rank=2,dist=0.51) sparse(rank=1,bm25=-19.0); Docs/file2.txt branch=dense rrf=0.01587 dense(rank=3,dist=0.52) sparse(rank=None,bm25=None); Docs/file9.txt branch=sparse rrf=0.01587 dense(rank=None,dist=None) sparse(rank=3,bm25=-11.0); Docs/file3.txt branch=dense rrf=0.01562 dense(rank=4,dist=0.95) sparse(rank=None,bm25=None); Docs/file4.txt branch=dense rrf=0.01538 dense(rank=5,dist=0.95) sparse(rank=None,bm25=None); Docs/file5.txt branch=dense rrf=0.01515 dense(rank=6,dist=0.95) sparse(rank=None,bm25=None); Docs/file6.txt branch=dense rrf=0.01493 dense(rank=7,dist=0.95) sparse(rank=None,bm25=None)",
    ],
    "no_relevant": ["QUERY 'what is x' -> not relevant, fallback disabled"],
    "general": ["QUERY 'what is x' -> general-knowledge fallback, Ns"],
    "embed_error": ["QUERY_EMBED_FAILED 'what is x': timed out"],
    "generation_error": ["QUERY_GENERATION_FAILED 'what is x': boom"],
}
OUTCOME_OF = {"answered": "answered", "no_relevant": "no_relevant", "general": "general_knowledge",
              "embed_error": "error", "generation_error": "error"}
FIELDS = {"schema", "ts", "query", "caller", "outcome", "error", "n_sources", "sources", "total_s", "embed_s",
          "retrieve_s", "gen_s", "gen_tokens", "tok_per_s", "distance_threshold", "min_hits"}


def read_jsonl(cfg):
    files = list(cfg.logs_dir.glob("query_*.jsonl"))
    assert len(files) == 1 and files[0].name == f"query_{date.today().isoformat()}.jsonl"
    return [json.loads(l) for l in files[0].read_text().splitlines()]


@pytest.mark.parametrize("scenario", list(GOLDEN_TEXT))
def test_text_log_unchanged(scenario, monkeypatch, tmp_path, caplog):          # T-LOG-2
    caplog.set_level(logging.INFO, logger="query")
    cfg = make_config(tmp_path)
    run(monkeypatch, cfg, Q, scenario, caller="mcp")
    lines = [re.sub(r"\d+\.\d\ds", "Ns", r.getMessage()) for r in caplog.records if r.name == "query"]
    assert lines == GOLDEN_TEXT[scenario]


@pytest.mark.parametrize("scenario", list(GOLDEN_TEXT))
@pytest.mark.parametrize("caller", ["cli", "http", "mcp"])
def test_jsonl_record_fields(scenario, caller, monkeypatch, tmp_path):          # T-LOG-1
    cfg = make_config(tmp_path)
    run(monkeypatch, cfg, Q, scenario, caller=caller)
    (rec,) = read_jsonl(cfg)
    assert set(rec) == FIELDS
    assert rec["caller"] == caller and rec["query"] == Q
    assert rec["outcome"] == OUTCOME_OF[scenario] and rec["outcome"] in OUTCOMES
    assert (rec["error"] is not None) == (rec["outcome"] == "error")
    assert rec["distance_threshold"] == 0.85 and rec["min_hits"] == 1
    if rec["outcome"] == "answered":
        assert rec["n_sources"] == 8 == len(rec["sources"])
        assert set(rec["sources"][0]) >= {"rel_path", "chunk_id", "branch", "rrf_score", "dense_rank",
                                          "dense_distance", "sparse_rank", "sparse_bm25"}
        assert all(rec[k] is not None for k in ("total_s", "embed_s", "retrieve_s", "gen_s"))
    else:
        assert rec["n_sources"] == 0


def test_default_caller_is_unknown(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    run(monkeypatch, cfg, Q, "answered")
    assert read_jsonl(cfg)[0]["caller"] == "unknown"


def test_jsonl_failure_never_breaks_a_query(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    cfg.logs_dir.chmod(0o555)            # unwritable: the answer must still be returned
    try:
        result = run(monkeypatch, cfg, Q, "answered", caller="cli")
    finally:
        cfg.logs_dir.chmod(0o755)
    assert result.answer == "an answer" and not result.error


def test_one_line_per_query_and_valid_json_when_query_has_quotes_and_newlines(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    tricky = 'he said "hi"\n### Task:\nsecond line'
    run(monkeypatch, cfg, tricky, "no_relevant", caller="http")
    run(monkeypatch, cfg, Q, "no_relevant", caller="http")
    recs = read_jsonl(cfg)
    assert [r["query"] for r in recs] == [tricky, Q]
