#!/usr/bin/env python3
"""Survey already-pulled Ollama models for OpenClaw's agent role: real GPU fit (via
`ollama ps`, not estimated from file size) and real pass/fail on the repeat-question
tool-call test (via scripts/live_agent_test.py's proven live mechanism — see
Doc/step-5-requirements.md §5f for why the local-curl approach this replaces cannot be
trusted). Does not pull or delete anything — survey-only, existing models already on
disk.

Usage:
    ./scripts/survey_models.py                       # survey the default candidate list
    ./scripts/survey_models.py --models a,b,c         # override the list
    ./scripts/survey_models.py --trials 2             # repeat-question trials per model
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_agent_test import DEFAULT_QUESTION, test_repeat_question

# Already-pulled, distinct-weights candidates (deduped by model ID from `ollama list`;
# the qwen3.6-16k/32k/64k/ngl16 tags all share qwen3.6:35b-a3b's weights and its already-
# known result, so not re-tested separately here).
DEFAULT_CANDIDATES = [
    "ollama/qwen2.5:7b-instruct",
    "ollama/llama3.1:8b",
    "ollama/llama3:8b",
    "ollama/mistral:latest",
    "ollama/qwen2.5:14b-instruct",
    "ollama/qwen2.5-coder:14b",
    "ollama/deepseek-coder-v2:16b",
    "ollama/deepseek-coder:6.7b",
    "ollama/qwen2.5-coder:32b",
    "ollama/qwen3:8b",            # known fail — included as a live cross-check
    "ollama/qwen3.6:35b-a3b",     # known pass — control
]


def ollama_ps_row(model_tag: str) -> str:
    """model_tag like 'ollama/qwen3:8b' -> the plain Ollama name 'qwen3:8b'."""
    name = model_tag.split("/", 1)[-1]
    try:
        r = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return f"(ollama ps failed: {e})"
    for line in r.stdout.splitlines()[1:]:
        if line.split() and line.split()[0] == name:
            return line
    return "(not resident — likely idled out before this check)"


def gpu_fit_pct(ps_row: str) -> str:
    for tok in ps_row.split():
        if "/" in tok and "%" in tok:
            # e.g. "67%/33%" (CPU/GPU) or "100%" alone
            parts = tok.replace("%", "").split("/")
            if len(parts) == 2:
                return f"{parts[1]}%"
            return f"{parts[0]}%"
        if tok == "100%":
            return "100%"
    return "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=None, help="Comma-separated override, e.g. ollama/mistral:latest,...")
    parser.add_argument("--trials", type=int, default=1, help="Repeat-question trials per model (default 1 for survey speed)")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()

    candidates = args.models.split(",") if args.models else DEFAULT_CANDIDATES
    rows = []

    for model in candidates:
        print(f"\n=== {model} ===", flush=True)
        t0 = time.monotonic()
        try:
            result = test_repeat_question(model, args.question, args.trials)
            passed = result["passes"] == result["of"] and result["of"] > 0
            detail = f"{result['passes']}/{result['of']}"
            errors = [r.get("error") for r in result["results"] if "error" in r]
        except Exception as e:
            passed, detail, errors = False, "crashed", [str(e)]
        elapsed = time.monotonic() - t0

        ps_row = ollama_ps_row(model)
        fit = gpu_fit_pct(ps_row)

        print(f"  repeat-test: {detail}  ({elapsed:.0f}s)")
        print(f"  residency:   {ps_row}")
        if errors:
            print(f"  errors:      {errors}")

        rows.append({
            "model": model, "pass": passed, "detail": detail,
            "gpu_fit": fit, "residency": ps_row, "errors": errors,
        })

    print(f"\n\n{'='*90}")
    print(f"{'model':<28}{'GPU fit':<10}{'repeat-test':<14}{'pass/fail'}")
    print("-" * 90)
    for r in rows:
        status = "PASS" if r["pass"] else ("ERROR" if r["errors"] else "FAIL")
        print(f"{r['model']:<28}{r['gpu_fit']:<10}{r['detail']:<14}{status}")
    print(f"{'='*90}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
