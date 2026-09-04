#!/usr/bin/env python3
"""Step 4 indexing entrypoint — embeds Step 3's pending chunks into LanceDB (dense)
and SQLite FTS5 (sparse), and cleans up chunks marked deleted from both stores.

Usage:
    ./run_index.py [--config config/index_config.yaml]

See Doc/step-4-requirements.md for the full spec. Reads manifest.db's `chunks` table
(Step 3 output, never modified except for embedding_status/purge bookkeeping here) and
populates lancedb/ + the chunks_fts virtual table in manifest.db. No retrieval, no
fusion, no LLM call — that's Step 5.
"""
from __future__ import annotations

import argparse
import logging
import time

from indexing.config import IndexConfig
from indexing.pipeline import run
from ingest.logging_setup import run_timestamp, setup_logging
from ingest.manifest import open_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/index_config.yaml", help="Path to index_config.yaml")
    args = parser.parse_args()

    config = IndexConfig.load(args.config)

    ts = run_timestamp()
    log_path = setup_logging(config.logs_dir, ts, logger_name="index")
    logger = logging.getLogger("index")

    logger.info("=== index run start %s ===", ts)
    logger.info("manifest_db=%s", config.manifest_db)
    logger.info("lancedb_dir=%s table=%s", config.lancedb_dir, config.lancedb_table)
    logger.info("ollama_url=%s embedding_model=%s batch_size=%d",
                config.ollama_url, config.embedding_model, config.embed_batch_size)
    logger.info("log_path=%s", log_path)

    start = time.monotonic()
    with open_manifest(config.manifest_db) as manifest:
        stats = run(config, manifest)
        chunk_counts = manifest.chunk_counts()

    elapsed = time.monotonic() - start

    logger.info("=== index run summary (%.1fs) ===", elapsed)
    print(f"\nIndex run complete in {elapsed:.1f}s.")
    print(f"{'metric':<24}{'count'}")
    for key in ("embedded_chunks", "embed_batches", "embed_batch_failures", "chunks_cleaned_up"):
        n = stats.get(key, 0)
        print(f"{key:<24}{n}")
        logger.info("  %-22s %d", key, n)

    print(f"\nchunks table embedding_status breakdown: {chunk_counts}")
    logger.info("chunks table embedding_status breakdown: %s", chunk_counts)

    print(f"\nLog: {log_path}")
    print(f"Manifest: {config.manifest_db}")
    print(f"LanceDB: {config.lancedb_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
