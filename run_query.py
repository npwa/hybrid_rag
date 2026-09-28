#!/usr/bin/env python3
"""Step 5 access point 1 — CLI. Calls the core query engine directly, in-process.

Usage:
    ./run_query.py --query "what is the adjusted gross income for 2024?" [--sources]

See Doc/step-5-requirements.md §3. Useful for testing before Open WebUI (§4) or
OpenClaw/Signal (§5) are wired up.
"""
from __future__ import annotations

import argparse

from query.config import QueryConfig
from query.engine import answer_query
from query.logging_setup import setup_query_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/query_config.yaml", help="Path to query_config.yaml")
    parser.add_argument("--query", required=True, help="The question to ask")
    parser.add_argument("--sources", action="store_true", help="Also print the retrieved source files")
    parser.add_argument("--scores", action="store_true",
                         help="Also print per-source retrieval detail: which leg(s) (dense/sparse/both) "
                              "found it, at what rank, raw per-leg score, and the fused RRF score")
    parser.add_argument("--allow-general-knowledge", action="store_true",
                         help="Override config: let the model answer from general knowledge when nothing relevant is found")
    args = parser.parse_args()

    config = QueryConfig.load(args.config)
    if args.allow_general_knowledge:
        config.allow_general_knowledge_fallback = True
    setup_query_logging(config.logs_dir)

    result = answer_query(args.query, config)

    if result.error:
        print(f"Error: {result.error}")
        return 1

    print(result.answer)
    if args.sources and result.sources:
        print("\nSources:")
        for s in result.sources:
            print(f"  - {s['rel_path']}")
    if args.scores and result.sources:
        print("\nRetrieval detail (which leg found each source, and at what score):")
        print(f"  {'branch':<14}{'rrf':<9}{'dense rank/dist':<20}{'sparse rank/bm25':<20}rel_path")
        for s in result.sources:
            dense = f"{s['dense_rank']}/{s['dense_distance']:.3f}" if s["dense_rank"] else "-"
            sparse = f"{s['sparse_rank']}/{s['sparse_bm25']:.3f}" if s["sparse_rank"] else "-"
            print(f"  {s['branch']:<14}{s['rrf_score']:<9}{dense:<20}{sparse:<20}{s['rel_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
