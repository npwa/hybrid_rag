"""T-GOLD-1/2: the gold question set runner, its report and API; T-DOC-1 helpers live in test_runbooks.py."""
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from console import gold
from console.api import create_app
from tests.conftest import ROOT

RUNNER = ROOT / "scripts" / "run_gold_set.py"
EXAMPLE = ROOT / "config" / "gold_questions.example.yaml"



@pytest.fixture()
def demo_cfg_file(demo_dir, tmp_path):
    """A console config whose demo_dir is the session's generated dataset (the CLI loads config files, not fixtures)."""
    raw = yaml.safe_load((ROOT / "config" / "console_config.example.yaml").read_text())
    raw["demo_dir"] = str(demo_dir)
    p = tmp_path / "console.yaml"
    p.write_text(yaml.safe_dump(raw))
    return p


def cli(cfg_file, *args, questions=EXAMPLE):
    r = subprocess.run([sys.executable, str(RUNNER), "--demo", "--config", str(cfg_file), "--questions", str(questions), *args],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


def test_baseline_run_passes_every_question(demo_cfg_file):                                      # T-GOLD-1
    rc, out, err = cli(demo_cfg_file, "--json")
    assert rc == 0, out + err
    rep = json.loads(out)
    assert rep["total"] == 8 and rep["passed"] == 8 and rep["failed"] == 0
    by_id = {r["id"]: r for r in rep["results"]}
    assert by_id["demo-07"]["verdict"] == "no_relevant" and by_id["demo-01"]["first_expected_rank"] is not None
    assert all(r["passed"] and r["problems"] == [] for r in rep["results"])


def test_text_report_lists_each_question(demo_cfg_file):
    rc, out, _ = cli(demo_cfg_file)
    assert rc == 0 and "Gold set: 8/8 passed" in out and out.count("[PASS]") == 8


def test_tightening_the_gate_makes_the_run_fail_and_names_why(demo_cfg_file):                    # T-GOLD-2
    rc, out, _ = cli(demo_cfg_file, "--set", "relevance_min_hits=30")
    assert rc == 1 and "[FAIL] demo-01" in out and "gate said no_relevant, expected answered" in out
    assert "min_hits=30" in out


def test_scratch_query_config_file_changes_the_result(demo_cfg_file, tmp_path):                  # T-GOLD-2 (scratch config)
    q = yaml.safe_load((ROOT / "config" / "query_config.yaml").read_text())
    q["relevance_min_hits"] = 30
    scratch = tmp_path / "scratch_query.yaml"
    scratch.write_text(yaml.safe_dump(q))
    rc, out, _ = cli(demo_cfg_file, "--query-config", str(scratch))
    assert rc == 1 and "[FAIL]" in out


def test_loosening_the_gate_fails_the_refusal_questions(demo_cfg_file):
    rc, out, _ = cli(demo_cfg_file, "--set", "relevance_distance_threshold=5")
    assert rc == 1 and "[FAIL] demo-07" in out and "gate said answered, expected no_relevant" in out


def test_baseline_comparison_reports_regressions_and_fixes(demo_cfg_file, demo_dir, tmp_path):
    rc, _, _ = cli(demo_cfg_file, "--save-baseline")
    assert rc == 0 and (demo_dir / "logs" / "gold_baseline.json").exists()
    try:
        rc, out, _ = cli(demo_cfg_file, "--set", "relevance_min_hits=30")
        assert rc == 1 and "regressions ['demo-01'" in out
        rc, out, _ = cli(demo_cfg_file)
        assert rc == 0 and "regressions none" in out
    finally:
        (demo_dir / "logs" / "gold_baseline.json").unlink(missing_ok=True)
        (demo_dir / "logs" / "gold_report.json").unlink(missing_ok=True)


def test_run_without_saving_writes_nothing(demo_cfg_file, demo_dir):
    cli(demo_cfg_file)
    assert not (demo_dir / "logs" / "gold_report.json").exists()


def test_bad_question_files_are_rejected(demo_cfg_file, tmp_path):
    cases = {"dup": [{"id": "a", "question": "x", "sources_any": ["p"]}, {"id": "a", "question": "y", "sources_any": ["p"]}],
             "no-sources": [{"id": "a", "question": "x"}],
             "bad-expect": [{"id": "a", "question": "x", "expect": "maybe"}],
             "empty": [{"id": "a", "question": ""}]}
    for name, qs in cases.items():
        f = tmp_path / f"{name}.yaml"
        f.write_text(yaml.safe_dump({"questions": qs}))
        rc, _, err = cli(demo_cfg_file, questions=f)
        assert rc == 2 and err.strip(), name
    rc, _, err = cli(demo_cfg_file, questions=tmp_path / "missing.yaml")
    assert rc == 2 and "no question file" in err
    rc, _, err = cli(demo_cfg_file, "--set", "nonsense=1")
    assert rc == 2 and "unknown query setting" in err


def test_compare_helper():
    base = {"results": [{"id": "a", "passed": True}, {"id": "b", "passed": False}]}
    rep = {"results": [{"id": "a", "passed": False}, {"id": "b", "passed": True}, {"id": "c", "passed": True}]}
    assert gold.compare(rep, base) == {"regressions": ["a"], "fixed": ["b"], "new": ["c"]}


@pytest.fixture()
def saved_report(demo_cfg_file, demo_dir):
    cli(demo_cfg_file, "--save-report")
    yield demo_dir / "logs" / "gold_report.json"
    (demo_dir / "logs" / "gold_report.json").unlink(missing_ok=True)


def test_api_without_a_saved_run(demo_config):
    d = TestClient(create_app(demo_config)).get("/api/v1/gold").json()
    assert d["available"] is False and "run_gold_set.py" in d["detail"]


def test_api_returns_the_saved_run(demo_config, saved_report):
    d = TestClient(create_app(demo_config)).get("/api/v1/gold").json()
    assert d["available"] and d["total"] == 8 and d["passed"] == 8 and len(d["items"]) == 8
    assert d["items"][0]["question"] == "when does the ferry to the island leave" and d["items"][0]["sources_any"]


def test_api_masks_questions_and_paths(demo_config, saved_report):                               # T-PRIV-2
    body = TestClient(create_app(dataclasses.replace(demo_config, mask_queries=True))).get("/api/v1/gold").text
    for secret in ("ferry", "mozart", "Travel/Trips", "Garden/Plans"):
        assert secret not in body, secret
    assert "[masked-" in body
