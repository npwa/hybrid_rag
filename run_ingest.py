#!/usr/bin/env python3
"""Step 1 ingestion entrypoint — discovery, classification, extraction.

Usage:
    ./run_ingest.py [--config config/ingest_config.yaml] [--limit N] [--export-jsonl PATH]

See step-1-requirements.md for the full spec. This script only walks the
source tree, classifies files, extracts normalized text, and records
everything in manifest.db — no chunking, embedding, or indexing (Step 2+).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from ingest.config import Config
from ingest.logging_setup import run_timestamp, setup_logging
from ingest.manifest import open_manifest
from ingest.pipeline import run

SUMMARY_STATUS_ORDER = [
    "extracted", "ocr_extracted", "ocr_low_confidence", "warning_empty_conversion",
    "failed", "encrypted", "empty", "skipped", "deleted",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/ingest_config.yaml", help="Path to ingest_config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files (testing; disables deleted-marking)")
    parser.add_argument("--export-jsonl", default=None, help="After the run, export the manifest to this JSONL path")
    args = parser.parse_args()

    config = Config.load(args.config)

    ts = run_timestamp()
    log_path = setup_logging(config.logs_dir, ts)
    logger = logging.getLogger("ingest")

    logger.info("=== ingest run start %s ===", ts)
    logger.info("source_root=%s", config.source_root)
    logger.info("manifest_db=%s", config.manifest_db)
    logger.info("log_path=%s", log_path)

    if not config.source_root.exists():
        logger.error("source_root does not exist or is not accessible: %s", config.source_root)
        print(f"ERROR: source_root does not exist or is not accessible: {config.source_root}", file=sys.stderr)
        return 2

    config.extracted_text_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    with open_manifest(config.manifest_db) as manifest:
        stats = run(config, manifest, limit=args.limit)

        status_counts = manifest.status_counts()
        category_counts = manifest.category_counts()

        if args.export_jsonl:
            n = manifest.export_jsonl(Path(args.export_jsonl))
            logger.info("Exported %d manifest rows to %s", n, args.export_jsonl)

    elapsed = time.monotonic() - start

    unclassified = category_counts.get("unclassified", 0)
    excluded_skipped = status_counts.get("skipped", 0) - unclassified

    logger.info("=== ingest run summary (%.1fs, %d files walked) ===", elapsed, stats["processed"])
    print(f"\nIngest run complete in {elapsed:.1f}s — {stats['processed']} files walked.")
    print(f"{'status':<26}{'count'}")
    for status in SUMMARY_STATUS_ORDER:
        if status == "skipped":
            print(f"{'skipped (excluded)':<26}{excluded_skipped}")
            print(f"{'unclassified':<26}{unclassified}")
            continue
        n = status_counts.get(status, 0)
        print(f"{status:<26}{n}")
        logger.info("  %-24s %d", status, n)
    logger.info("  %-24s %d", "skipped (excluded)", excluded_skipped)
    logger.info("  %-24s %d", "unclassified", unclassified)

    print(f"\nLog: {log_path}")
    print(f"Manifest: {config.manifest_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
