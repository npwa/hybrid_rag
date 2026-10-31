"""T-ENG-1: query.engine.answer_query behaves exactly as before the retrieve() extraction.

tests/golden/engine_results.json was captured from the engine BEFORE the refactor, with stubbed embedding,
dense/sparse search and generation (tests/engine_harness.py). It pins, per scenario: the QueryResult (answer,
sources with per-leg ranks and scores, error, general_knowledge flag) and every call made to a dependency
(embed input, dense vector and limit, sparse table/query/limit, generation system+user prompts, in order)."""
import dataclasses
import json
from pathlib import Path

import pytest

from tests import engine_harness as h

GOLDEN = json.loads((Path(__file__).parent / "golden" / "engine_results.json").read_text())


@pytest.mark.parametrize("case", GOLDEN, ids=[f"{g['scenario']}-{i}" for i, g in enumerate(GOLDEN)])
def test_answer_query_unchanged(case, monkeypatch, tmp_path):
    cfg = h.make_config(tmp_path)
    for k, v in case["overrides"].items():
        setattr(cfg, k, v)
    result = h.run(monkeypatch, cfg, "what is x", case["scenario"])
    assert json.loads(json.dumps(dataclasses.asdict(result))) == case["result"]
    assert json.loads(json.dumps([list(c) for c in h.CALLS])) == case["calls"]
