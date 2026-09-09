#!/usr/bin/env python3
"""Evaluate Ollama models for OpenClaw agent tool-calling reliability.

Not part of the RAG pipeline itself — an ops tool for re-running the exact battery of
real-world failure modes discovered while debugging the OpenClaw/Signal integration
(Doc/step-5-requirements.md §5), against any candidate model, whenever a new model is
pulled or Ollama is updated. Extracts the current `ask_documents` tool description
directly from query/mcp_server.py at run time, so it can't silently drift out of sync
with what OpenClaw actually sees in production.

Usage:
    ./scripts/eval_tool_calling_models.py [model ...]
    (defaults to a candidate list if none given)
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
import urllib.request

OLLAMA_URL = "http://localhost:11434"

DEFAULT_MODELS = [
    "qwen3:8b",
    "qwen2.5:7b-instruct",
    "qwen2.5-coder:14b",
    "deepseek-coder-v2:16b",
    "llama3.1:8b",
    "llama3:8b",
    "qwen2.5-coder:32b",
    "qwen3.6:35b-a3b",
    "qwen3.6-ngl16:latest",
]

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search", "description": "Search the web",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "Fetch a URL",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    }},
    {"type": "function", "function": {
        "name": "memory_search", "description": "Search prior conversation memory",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "read", "description": "Read a local workspace file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write", "description": "Write a local workspace file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    }},
]

SYSTEM_PROMPT = (
    "You are a helpful personal assistant with access to several tools. Use web_search "
    "for current events, web_fetch to retrieve a URL, memory_search to recall prior "
    "conversation notes, read/write for local workspace files, and hybrid-rag__ask_documents "
    "as described in its own tool description below. Always pick the single most "
    "appropriate tool rather than guessing from general knowledge."
)


def load_ask_documents_description() -> str:
    src = open("query/mcp_server.py").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "ask_documents":
            return ast.get_docstring(node)
    raise RuntimeError("could not find ask_documents docstring in query/mcp_server.py")


def build_tools(ask_documents_description: str) -> list[dict]:
    return TOOLS + [{
        "type": "function", "function": {
            "name": "hybrid-rag__ask_documents",
            "description": ask_documents_description,
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    }]


def make_case(name: str, user_message: str, expect_tool: str | None, extra_history: list[dict] | None = None):
    """expect_tool: tool name that must be called, or None if no tool call is expected."""
    return {"name": name, "user_message": user_message, "expect_tool": expect_tool, "extra_history": extra_history or []}


CASES = [
    make_case(
        "personal_fact_direct",
        "United Mileage plus account number?",
        "hybrid-rag__ask_documents",
    ),
    make_case(
        "general_knowledge_no_trigger",
        "What is the capital of France?",
        None,
    ),
    make_case(
        "memory_vs_documents_followup",
        "How much did the Thule box sell for?",
        "hybrid-rag__ask_documents",
        extra_history=[
            {"role": "user", "content": "How big is the roof top cargo box?"},
            {"role": "assistant", "content": "The Thule Evolution 1800 is 91.3 in x 31 in x 16.2 in, 18 cu.ft."},
        ],
    ),
]


def chat(model: str, messages: list[dict], tools: list[dict]) -> dict:
    payload = json.dumps({"model": model, "stream": False, "think": False, "messages": messages, "tools": tools}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=payload, headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    elapsed = time.monotonic() - start
    return body, elapsed


def ollama_ps_row(model: str) -> str:
    out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
    for line in out.splitlines()[1:]:
        if line.split()[0] == model.split(":")[0] or model in line:
            return line.strip()
    return "(not resident)"


def run_case(model: str, description: str, case: dict) -> dict:
    tools = build_tools(description)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + case["extra_history"] + [
        {"role": "user", "content": case["user_message"]}
    ]
    try:
        body, elapsed = chat(model, messages, tools)
    except Exception as e:
        return {"case": case["name"], "pass": False, "detail": f"ERROR: {e}", "elapsed": None}

    msg = body.get("message", {})
    tool_calls = msg.get("tool_calls") or []
    called_names = [tc["function"]["name"] for tc in tool_calls]
    structured = bool(tool_calls)
    content = (msg.get("content") or "").strip()

    if case["expect_tool"] is None:
        ok = not called_names
        detail = "no tool call (correct)" if ok else f"unexpectedly called {called_names}"
    else:
        # Detect the common failure mode: tool call dumped as text instead of tool_calls
        looks_like_pseudo_call = (not structured) and case["expect_tool"] in content
        if case["expect_tool"] in called_names:
            ok = True
            detail = f"called {case['expect_tool']} (structured)"
        elif looks_like_pseudo_call:
            ok = False
            detail = "tool call emitted as TEXT, not structured tool_calls field"
        elif called_names:
            ok = False
            detail = f"called wrong tool: {called_names}"
        else:
            ok = False
            detail = f"declined / answered directly: {content[:120]!r}"

    return {"case": case["name"], "pass": ok, "detail": detail, "elapsed": elapsed}


def main() -> int:
    models = sys.argv[1:] or DEFAULT_MODELS
    description = load_ask_documents_description()

    results = []
    for model in models:
        print(f"\n=== {model} ===")
        model_results = []
        for case in CASES:
            r = run_case(model, description, case)
            model_results.append(r)
            status = "PASS" if r["pass"] else "FAIL"
            t = f"{r['elapsed']:.1f}s" if r["elapsed"] is not None else "-"
            print(f"  [{status}] {r['case']:<28} {t:>7}  {r['detail']}")
        ps_row = ollama_ps_row(model)
        print(f"  ollama ps: {ps_row}")
        results.append({"model": model, "results": model_results, "ollama_ps": ps_row})

    print("\n\n=== Summary ===")
    print(f"{'model':<26}{'pass':<8}{'avg_s':<8}{'cpu/gpu split'}")
    for r in results:
        n_pass = sum(1 for c in r["results"] if c["pass"])
        times = [c["elapsed"] for c in r["results"] if c["elapsed"] is not None]
        avg = sum(times) / len(times) if times else 0.0
        split = "?"
        parts = r["ollama_ps"].split()
        for p in parts:
            if "CPU" in p or "GPU" in p:
                split = p
        print(f"{r['model']:<26}{n_pass}/{len(CASES):<6}{avg:<8.1f}{split}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
