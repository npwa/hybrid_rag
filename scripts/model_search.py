#!/usr/bin/env python3
"""Brute-force search for a model that both fits this GPU and reliably calls
hybrid-rag__ask_documents under OpenClaw's real workspace prompt — see
Doc/step-5-requirements.md §5a/5c for why this is needed: qwen3:8b passed every
isolated/concurrent test twice and still failed live both times on the repeat-question
case, so this harness treats that case as the dominant pass/fail signal, run many times,
not a single yes/no check.

For each candidate: pull -> check `tools` capability + GPU residency -> run the full
test battery, weighted heavily toward REPEAT_TRIALS repeats of the repeat-question case
-> keep the model if it clears PASS_THRESHOLD, otherwise `ollama rm` it to free disk
immediately. Writes one JSON line per candidate to --report as it goes (so a partial
run is never lost), plus a human-readable summary at the end.

This is Stage 1 only (see the plan) — automated, unattended elimination of bad
candidates. Anything that survives still needs live Signal testing before being trusted;
this script cannot and does not claim to replace that.

Usage:
    ./scripts/model_search.py                      # run the default candidate list
    ./scripts/model_search.py --candidates a,b,c    # override the list
    ./scripts/model_search.py --dry-run             # score already-pulled models only,
                                                     # no pull/no delete (for validating
                                                     # the harness itself)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_tool_calling_models import CASES, build_tools, chat, load_ask_documents_description

# Models currently in real use anywhere in this project — never pulled over, never
# deleted, regardless of how they'd score.
PROTECTED = {
    "qwen3:8b", "nomic-embed-text", "nomic-embed-text:latest",
    "qwen3.6:35b-a3b", "qwen3.6:latest", "qwen3.6-ngl16:latest",
    "qwen3.6-16k:latest", "qwen3.6-32k:latest", "qwen3.6-64k:latest",
}

# Researched candidates (Doc/step-5-requirements.md's model-search plan) — models
# tagged `tools`-capable in Ollama's library, in roughly the 10GB-fitting range, not
# already tried and ruled out (mistral, llama3.1:8b, qwen2.5(-coder) family, qwen3:8b,
# qwen3.6:35b-a3b all failed real criteria already — see step-5-requirements.md §5).
# Tags are best-effort from research, not pre-verified against the live library — a
# wrong/retired tag just fails the pull step and gets logged, not fatal to the run.
DEFAULT_CANDIDATES = [
    "llama3-groq-tool-use:8b",
    "granite3.1-dense:8b",
    "granite3-dense:8b",
    "gemma3:9b",
    "gemma3:12b",
    "phi4:14b",
    "hermes3:8b",
    "firefunction-v2",
]

REPEAT_TRIALS = 10          # the single most discriminating test — see docstring
MIN_REPEAT_PASSES = 10      # require a clean sweep, since qwen3:8b looked clean too
PULL_TIMEOUT_S = 1200       # 20 min cap per model pull
GARBLED_QUERIES = [
    ("what is the Usdfed mierwege account number?", None),       # garbled, novel topic
    ("what is the SKU number for JDSHFfff meigling product?", None),
]


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ollama_pull(model: str) -> tuple[bool, str]:
    try:
        r = run(["ollama", "pull", model], timeout=PULL_TIMEOUT_S)
        return r.returncode == 0, (r.stderr or r.stdout)[-500:]
    except subprocess.TimeoutExpired:
        return False, f"pull timed out after {PULL_TIMEOUT_S}s"


def ollama_rm(model: str) -> None:
    if model in PROTECTED:
        raise RuntimeError(f"refusing to delete protected model {model!r}")
    run(["ollama", "rm", model])


def ollama_show(model: str) -> dict:
    r = run(["ollama", "show", model], timeout=30)
    text = r.stdout
    return {
        "tools_capable": "tools" in text.lower().split("capabilities", 1)[-1].split("\n\n")[0].lower()
                          if "capabilities" in text.lower() else False,
        "raw": text,
    }


def ollama_ps_residency(model: str) -> str:
    r = run(["ollama", "ps"], timeout=15)
    for line in r.stdout.splitlines()[1:]:
        if line.split() and line.split()[0] == model:
            return line
    return "(not resident)"


def build_system_prompt() -> str:
    root = Path(__file__).resolve().parent.parent
    soul = (root / "openclaw-workspace" / "SOUL.md").read_text()
    agents = (root / "openclaw-workspace" / "AGENTS.md").read_text()
    user = (root / "openclaw-workspace" / "USER.md").read_text()
    return f"{soul}\n\n---\n\n{agents}\n\n---\n\n{user}"


def test_repeat_question(model: str, tools: list[dict], system_prompt: str) -> dict:
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "United Mileage plus account number?"},
        {"role": "assistant", "content": "Your United MileagePlus account number is PLL60xxxxxxxxx."},
    ]
    passes = 0
    details = []
    for i in range(REPEAT_TRIALS):
        messages = history + [{"role": "user", "content": "United Mileage plus account number?"}]
        try:
            body, elapsed = chat(model, messages, tools)
        except Exception as e:
            details.append(f"run{i+1}: ERROR {e}")
            continue
        msg = body.get("message", {})
        called = [tc["function"]["name"] for tc in (msg.get("tool_calls") or [])]
        ok = called == ["hybrid-rag__ask_documents"]
        passes += ok
        details.append(f"run{i+1}: {'OK' if ok else 'FAIL'} called={called} ({elapsed:.1f}s)")
    return {"passes": passes, "of": REPEAT_TRIALS, "details": details}


def test_garbled_sequence(model: str, tools: list[dict], system_prompt: str) -> dict:
    """Checks for the fixation/fabrication failure found with qwen3:8b under
    thinking=false: does the model stay sane (decline or correctly re-query) on
    nonsense input after a real prior answer, rather than fixating or inventing
    plausible-looking details for unrelated follow-ups."""
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "what is the United mileage plus account number?"},
        {"role": "assistant", "content": "Your United MileagePlus account number is PLL69373."},
    ]
    results = []
    for query, _ in GARBLED_QUERIES:
        history.append({"role": "user", "content": query})
        try:
            body, elapsed = chat(model, history, tools)
        except Exception as e:
            results.append({"query": query, "error": str(e)})
            continue
        msg = body.get("message", {})
        called = [tc["function"]["name"] for tc in (msg.get("tool_calls") or [])]
        content = (msg.get("content") or "")[:150]
        # Fixation red flag: it restates the earlier account number for an unrelated query.
        fixated = "69373" in content
        results.append({"query": query, "called": called, "content": content, "fixated": fixated})
        history.append(msg)
    return {"results": results, "any_fixated": any(r.get("fixated") for r in results)}


def score_candidate(model: str) -> dict:
    description = load_ask_documents_description()
    tools = build_tools(description)
    system_prompt = build_system_prompt()

    result = {"model": model, "timestamp": time.time()}

    show = ollama_show(model)
    result["tools_capable"] = show["tools_capable"]
    if not show["tools_capable"]:
        result["pass"] = False
        result["reason"] = "not tagged tools-capable after pull"
        return result

    # Touch the model once so `ollama ps` reflects real residency, not a stale read.
    try:
        chat(model, [{"role": "user", "content": "hi"}], tools)
    except Exception as e:
        result["pass"] = False
        result["reason"] = f"warm-up call failed: {e}"
        return result
    result["residency"] = ollama_ps_residency(model)

    case_results = []
    for case in CASES:
        try:
            messages = [{"role": "system", "content": system_prompt}] + case["extra_history"] + [
                {"role": "user", "content": case["user_message"]}
            ]
            body, elapsed = chat(model, messages, tools)
            msg = body.get("message", {})
            called = [tc["function"]["name"] for tc in (msg.get("tool_calls") or [])]
            if case["expect_tool"] is None:
                ok = not called
            else:
                ok = called == [case["expect_tool"]]
            case_results.append({"case": case["name"], "pass": ok, "called": called})
        except Exception as e:
            case_results.append({"case": case["name"], "pass": False, "error": str(e)})
    result["cases"] = case_results
    cases_pass = all(c["pass"] for c in case_results)

    result["repeat_question"] = test_repeat_question(model, tools, system_prompt)
    repeat_pass = result["repeat_question"]["passes"] >= MIN_REPEAT_PASSES

    result["garbled_sequence"] = test_garbled_sequence(model, tools, system_prompt)
    garbled_pass = not result["garbled_sequence"]["any_fixated"]

    gpu_resident = "100% GPU" in result["residency"] or "0%/100% CPU/GPU" not in result["residency"]
    result["gpu_resident_ok"] = "CPU" not in result["residency"] or result["residency"].split()[2].startswith("0%")

    result["pass"] = cases_pass and repeat_pass and garbled_pass
    result["reason"] = (
        "PASS" if result["pass"] else
        f"cases_pass={cases_pass} repeat={result['repeat_question']['passes']}/{REPEAT_TRIALS} "
        f"garbled_ok={garbled_pass}"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", default=None, help="Comma-separated model list, overrides the default")
    parser.add_argument("--report", default="scripts/model_search_report.jsonl")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only score already-pulled models; never pull or delete")
    args = parser.parse_args()

    candidates = args.candidates.split(",") if args.candidates else DEFAULT_CANDIDATES
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    survivors = []
    for model in candidates:
        print(f"\n{'='*70}\n=== {model} ===\n{'='*70}")
        entry = {"model": model}

        if not args.dry_run:
            print(f"pulling {model} ...")
            ok, msg = ollama_pull(model)
            entry["pull_ok"] = ok
            if not ok:
                entry["pull_error"] = msg
                print(f"  PULL FAILED: {msg}")
                with report_path.open("a") as f:
                    f.write(json.dumps(entry) + "\n")
                continue

        print("scoring ...")
        try:
            result = score_candidate(model)
        except Exception as e:
            result = {"model": model, "pass": False, "reason": f"scoring crashed: {e}"}
        entry.update(result)

        print(f"  -> {entry.get('reason')}")
        with report_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        if entry.get("pass"):
            survivors.append(model)
            print(f"  KEEPING {model} (Stage 2 candidate)")
        elif not args.dry_run and model not in PROTECTED:
            print(f"  deleting {model} ...")
            ollama_rm(model)

    print(f"\n\n{'='*70}\nSUMMARY — Stage 2 candidates (passed Stage 1, need live Signal testing): {survivors}\n{'='*70}")
    print(f"Full report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
