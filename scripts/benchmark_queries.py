#!/usr/bin/env python3
"""Small benchmark: run a fixed set of real questions through the actual query engine
(query.engine.answer_query() — the exact same path the CLI/HTTP/MCP access points use,
not a re-implementation of it) and report wall time + generation tok/sec for each.

Usage:
    ./scripts/benchmark_queries.py [--config config/query_config.yaml] [--runs N] [--questions FILE]

Token/throughput numbers come straight from Ollama's /api/chat response
(eval_count/eval_duration — see query/generation.py's GenerationMetrics), not an
estimate. --runs > 1 repeats each question and reports mean + stdev, since the first
call after a model's been idle pays a one-time load cost (see Doc/step-5-requirements.md
§5a on OLLAMA_KEEP_ALIVE) that would otherwise skew a single-run number.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

# This script lives in scripts/, one level below the project root where the query/
# package actually is — unlike run_query.py, Python won't find `query` on sys.path
# without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from query.config import QueryConfig
from query.engine import answer_query
from query.logging_setup import setup_query_logging

DEFAULT_QUESTIONS = [
    "How much was the hotel for Maryse in Zurich?",
    "What is the status on the positions at LegitScript?",
    "What is the court case number for Mattias criminal case?",
    "How big is the roof top cargo box?",
    "What is the United mileage plus account number?",
    "What was the invoice number and amount paid to Balboa Fence Company in 2022?",
]


def fmt(x: float | None, suffix: str = "") -> str:
    return f"{x:.2f}{suffix}" if x is not None else "-"


def mean_stdev(vals: list[float]) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    if len(vals) == 1:
        return f"{vals[0]:.2f}"
    return f"{statistics.mean(vals):.2f} (±{statistics.stdev(vals):.2f})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/query_config.yaml")
    parser.add_argument("--runs", type=int, default=1, help="Repeat each question this many times")
    parser.add_argument("--questions", default=None,
                         help="Path to a text file, one question per line (default: 6 built-in sample questions)")
    args = parser.parse_args()

    config = QueryConfig.load(args.config)
    setup_query_logging(config.logs_dir)

    if args.questions:
        with open(args.questions, encoding="utf-8") as f:
            questions = [line.strip() for line in f if line.strip()]
    else:
        questions = DEFAULT_QUESTIONS

    print(f"Benchmarking {len(questions)} question(s) x {args.runs} run(s) against "
          f"model={config.generation_model!r} (think={config.think}, num_ctx={config.num_ctx})\n")

    all_rows = []
    for q in questions:
        print(f"Q: {q}")
        wall_times, gen_tps, gen_toks = [], [], []
        for run in range(args.runs):
            t0 = time.monotonic()
            result = answer_query(q, config)
            wall = time.monotonic() - t0

            if result.error:
                print(f"  [run {run + 1}/{args.runs}] ERROR: {result.error}")
                continue

            tps = (result.gen_tokens / result.gen_seconds
                   if result.gen_tokens and result.gen_seconds else None)
            wall_times.append(wall)
            if tps is not None:
                gen_tps.append(tps)
            if result.gen_tokens is not None:
                gen_toks.append(result.gen_tokens)

            run_label = f"  [run {run + 1}/{args.runs}] " if args.runs > 1 else "  "
            print(f"{run_label}wall={wall:.2f}s gen_tokens={result.gen_tokens} tok/s={fmt(tps)}")
            # The actual point of printing this at all: a fast, well-sourced answer
            # that's wrong isn't a result worth having. Full text, not a preview —
            # truncating it is exactly what would hide the failure you're checking for.
            print(f"  A: {result.answer}")
            if result.sources:
                print(f"     sources: {', '.join(s['rel_path'] for s in result.sources[:3])}"
                      f"{', ...' if len(result.sources) > 3 else ''}")
        print()

        all_rows.append({
            "question": q,
            "wall": mean_stdev(wall_times),
            "tok_s": mean_stdev(gen_tps),
            "tokens": mean_stdev([float(t) for t in gen_toks]) if gen_toks else "-",
        })

    print(f"\n{'question':<58}{'wall (s)':<16}{'gen tok/s':<16}{'gen tokens'}")
    print("-" * 103)
    for row in all_rows:
        q = row["question"][:52] + ("..." if len(row["question"]) > 52 else "")
        print(f"{q:<58}{row['wall']:<16}{row['tok_s']:<16}{row['tokens']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
