"""Gold question set (requirements Q-1): real questions with the documents that must be found, run through the
engine's retrieval (the same `retrieve()` production uses) to detect regressions when settings or the index change.

Question file (YAML):
    questions:
      - id: g01                       # stable id
        question: "when did I last fly to Palo Alto"
        expect: answered              # gate verdict: answered (default) | no_relevant
        sources_any: ["Travel/README"]   # substrings of rel_path; at least one must be in the fused top `within`
        within: 5                     # default: all fused results (top_k_fused)
        note: "why this question exists"
A question passes when the gate verdict equals `expect` and, for `answered`, one of `sources_any` is within the top `within`.
Retrieval only: no language model is called, so a run takes seconds and is safe to repeat. Real questions are personal data:
keep them in the git-ignored config/gold_questions.yaml; the tracked config/gold_questions.example.yaml fits the demo dataset."""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

REPORT_NAME = "gold_report.json"


def load_questions(path: str | Path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    out, seen = [], set()
    for i, q in enumerate(raw.get("questions", []), start=1):
        qid = str(q.get("id") or f"q{i:02d}")
        if qid in seen:
            raise ValueError(f"duplicate gold question id {qid}")
        seen.add(qid)
        expect = q.get("expect", "answered")
        if expect not in ("answered", "no_relevant"):
            raise ValueError(f"{qid}: expect must be answered or no_relevant, not {expect!r}")
        if not q.get("question"):
            raise ValueError(f"{qid}: question is empty")
        if expect == "answered" and not q.get("sources_any"):
            raise ValueError(f"{qid}: an answered question needs sources_any (substrings of the expected file paths)")
        out.append({"id": qid, "question": str(q["question"]), "expect": expect, "sources_any": list(q.get("sources_any") or []),
                    "within": q.get("within"), "note": q.get("note", "")})
    return out


def run(questions: list[dict], qcfg, embed=None) -> dict:
    from query.engine import retrieve
    t0 = time.monotonic()
    results = []
    for q in questions:
        r = retrieve(q["question"], qcfg, full=True, embed=embed)
        verdict = "answered" if r.relevant else "no_relevant"
        paths = [c.get("rel_path") or "" for c in (r.fused or [])]
        within = int(q["within"] or len(paths) or 1)
        rank = next((i for i, p in enumerate(paths, start=1) if any(s in p for s in q["sources_any"])), None)
        problems = []
        if verdict != q["expect"]:
            problems.append(f"gate said {verdict}, expected {q['expect']}")
        if q["expect"] == "answered" and (rank is None or rank > within):
            problems.append("expected source not found" if rank is None else f"expected source only at rank {rank} (limit {within})")
        results.append({"id": q["id"], "question": q["question"], "expect": q["expect"], "verdict": verdict, "passed": not problems,
                        "problems": problems, "hits": r.hits, "nearest_distance": None if not r.dense else round(r.dense[0]["_distance"], 4),
                        "sources_any": q["sources_any"], "within": within, "first_expected_rank": rank, "top_sources": paths[:3]})
    passed = sum(1 for r in results if r["passed"])
    return {"settings": {"distance_threshold": qcfg.relevance_distance_threshold, "min_hits": qcfg.relevance_min_hits,
                         "top_k_fused": qcfg.top_k_fused, "rrf_k": qcfg.rrf_k},
            "total": len(results), "passed": passed, "failed": len(results) - passed,
            "seconds": round(time.monotonic() - t0, 2), "results": results}


def compare(report: dict, baseline: dict) -> dict:
    """Questions whose pass/fail differs from a saved baseline report."""
    before = {r["id"]: r["passed"] for r in baseline.get("results", [])}
    regressions = [r["id"] for r in report["results"] if before.get(r["id"]) is True and not r["passed"]]
    fixed = [r["id"] for r in report["results"] if before.get(r["id"]) is False and r["passed"]]
    new = [r["id"] for r in report["results"] if r["id"] not in before]
    return {"regressions": regressions, "fixed": fixed, "new": new}


def load_report(logs_dir: Path) -> dict | None:
    p = Path(logs_dir) / REPORT_NAME
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
