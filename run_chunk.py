#!/usr/bin/env python3
"""Step 3 chunking entrypoint — splits Step 1/2's extracted text into
retrieval-sized chunks with source-traceable metadata.

Usage:
    ./run_chunk.py [--config config/chunk_config.yaml] [--limit N] [--workers N]

See Doc/step-3-requirements.md for the full spec. Reads manifest.db + extracted_text/
(Step 1/2 output, never modified) and populates the `chunks` table in manifest.db with
embedding_status='pending' rows. No embedding, no vector DB, no BM25 index — that's
Step 4.
"""
from __future__ import annotations

import argparse
import logging
import time

from chunking.config import ChunkConfig
from chunking.pipeline import run
from ingest.logging_setup import run_timestamp, setup_logging
from ingest.manifest import open_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/chunk_config.yaml", help="Path to chunk_config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files (testing; disables deleted-marking)")
    parser.add_argument("--workers", type=int, default=None, help="Override max_workers from config (process pool size)")
    args = parser.parse_args()

    config = ChunkConfig.load(args.config)
    if args.workers is not None:
        config.max_workers = args.workers

    ts = run_timestamp()
    log_path = setup_logging(config.logs_dir, ts, logger_name="chunk")
    logger = logging.getLogger("chunk")

    logger.info("=== chunk run start %s ===", ts)
    logger.info("manifest_db=%s", config.manifest_db)
    logger.info("extracted_text_dir=%s", config.extracted_text_dir)
    logger.info("chunk_target_chars=%d chunk_overlap_chars=%d min_section_chars=%d max_workers=%d",
                config.chunk_target_chars, config.chunk_overlap_chars, config.min_section_chars, config.max_workers)
    logger.info("log_path=%s", log_path)

    start = time.monotonic()
    with open_manifest(config.manifest_db) as manifest:
        stats = run(config, manifest, limit=args.limit)
        chunk_counts = manifest.chunk_counts()

    elapsed = time.monotonic() - start

    logger.info("=== chunk run summary (%.1fs) ===", elapsed)
    print(f"\nChunk run complete in {elapsed:.1f}s — {stats['files_considered']} files considered.")
    print(f"{'metric':<28}{'count'}")
    for key in ("unchanged", "chunked", "empty_text", "read_error", "failed", "chunks_created", "chunks_marked_deleted"):
        n = stats.get(key, 0)
        print(f"{key:<28}{n}")
        logger.info("  %-26s %d", key, n)

    print(f"\nchunks table embedding_status breakdown: {chunk_counts}")
    logger.info("chunks table embedding_status breakdown: %s", chunk_counts)

    print(f"\nLog: {log_path}")
    print(f"Manifest: {config.manifest_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
