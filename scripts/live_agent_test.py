#!/usr/bin/env python3
"""The actually-reliable test we were missing — see Doc/step-5-requirements.md §5f.

Every prior test in this project (scripts/eval_tool_calling_models.py, model_search.py)
built its own approximation of OpenClaw's system prompt and conversation history, then
called Ollama directly. That approach was validated and found fundamentally blind: it
scored qwen3:8b as 10/10 reliable on the repeat-question case while that exact case was
a confirmed, repeated LIVE failure. The missing ingredient was never prompt content —
it was OpenClaw's own real session/history machinery, which a hand-built "fake assistant
turn in a messages array" never faithfully replicated.

This module drives OpenClaw's own `openclaw agent` CLI directly over SSH instead of
reconstructing anything: real session continuity, real workspace files, real injected
skills, real tool list, real sandboxing — the actual system, with only the model
swapped via --model (so production's agents.defaults.model.primary is never touched).
Confirmed by validation: reproduces the exact known qwen3:8b repeat-question failure on
the first try, and correctly passes the qwen3.6:35b-a3b control both times.

Cost note: each call is a real agent turn against real Ollama — seconds to several
minutes depending on the model. This is not cheap to run at scale; trial counts should
reflect that, not the trial counts used when isolated curl calls were cheap.

Prerequisite: agents.defaults.modelPolicy.allow must permit the model(s) being tested
(a `--model` override is still gated by this policy). Broadened to ["ollama/*"] for this
testing effort — see step-5-requirements.md §5f for the exact value to restore when
testing concludes.

Usage:
    ./scripts/live_agent_test.py --model ollama/qwen3:8b --trials 3
    ./scripts/live_agent_test.py --model ollama/qwen3.6:35b-a3b --trials 2 --question "..."
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid

SSH_KEY = "~/.ssh/claude/id_claude_ed25519"
SSH_HOST = "nick@npabot-u24"
OPENCLAW_BIN = "~/.npm-global/bin/openclaw"
DEFAULT_QUESTION = "What is the United mileage plus account number?"
CALL_TIMEOUT_S = 600  # openclaw agent's own default timeout is 600s; match it


def run_agent(session_key: str, model: str, message: str) -> dict:
    """One real agent turn via the actual OpenClaw gateway. Never delivers anywhere
    (no --deliver) and never touches production conversation history (caller-chosen
    session_key, not agent:main:main)."""
    remote_cmd = (
        f"{OPENCLAW_BIN} agent --session-key '{session_key}' --model '{model}' "
        f"--message {json.dumps(message)} --json"
    )
    proc = subprocess.run(
        ["ssh", "-i", SSH_KEY, SSH_HOST, remote_cmd],
        capture_output=True, text=True, timeout=CALL_TIMEOUT_S + 30,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": f"non-JSON output (exit {proc.returncode}): {proc.stdout[:300]} {proc.stderr[:300]}"}
    if data.get("ok") is False:
        return {"error": data.get("error", {}).get("message", "unknown CLI error")}
    meta = data["result"]["meta"]
    return {
        "text": data["result"]["payloads"][0]["text"],
        "tools_called": meta.get("toolSummary", {}).get("tools") or [],
        "duration_ms": meta.get("durationMs"),
        "context_tokens": meta.get("agentMeta", {}).get("contextTokens"),
    }


def test_repeat_question(model: str, question: str, trials: int) -> dict:
    """The one test that's actually caught every real failure in this project so far.
    Each trial: fresh session, ask once, ask again verbatim, check the SECOND call
    still invokes the tool rather than answering from the first call's cached reply."""
    results = []
    for i in range(trials):
        session_key = f"agent:main:livetest-{uuid.uuid4().hex[:8]}"
        r1 = run_agent(session_key, model, question)
        if "error" in r1:
            results.append({"trial": i + 1, "pass": False, "error": f"call1: {r1['error']}"})
            continue
        r2 = run_agent(session_key, model, question)
        if "error" in r2:
            results.append({"trial": i + 1, "pass": False, "error": f"call2: {r2['error']}"})
            continue
        ok = "hybrid-rag__ask_documents" in r2["tools_called"]
        results.append({
            "trial": i + 1, "pass": ok,
            "call1_tools": r1["tools_called"], "call1_ms": r1["duration_ms"],
            "call2_tools": r2["tools_called"], "call2_ms": r2["duration_ms"],
            "call2_text": r2["text"][:150],
        })
        # Hygiene: reset the throwaway session rather than leaving it dangling.
        run_agent(session_key, model, "/new")
    passes = sum(r["pass"] for r in results)
    return {"model": model, "passes": passes, "of": trials, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="e.g. ollama/qwen3:8b")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()

    print(f"Testing {args.model!r}, {args.trials} trial(s) of the repeat-question case ...")
    t0 = time.monotonic()
    result = test_repeat_question(args.model, args.question, args.trials)
    elapsed = time.monotonic() - t0

    for r in result["results"]:
        if "error" in r:
            print(f"  trial {r['trial']}: ERROR — {r['error']}")
        else:
            status = "PASS" if r["pass"] else "FAIL"
            print(f"  trial {r['trial']}: {status}  call1={r['call1_tools']} ({r['call1_ms']}ms)  "
                  f"call2={r['call2_tools']} ({r['call2_ms']}ms)")
            if not r["pass"]:
                print(f"    call2 answered: {r['call2_text']!r}")

    print(f"\n{result['model']}: {result['passes']}/{result['of']} passed ({elapsed:.0f}s total)")
    return 0 if result["passes"] == result["of"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
