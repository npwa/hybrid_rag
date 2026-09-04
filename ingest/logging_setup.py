"""One structured log file per run — §7."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def setup_logging(logs_dir: Path, run_ts: str, logger_name: str = "ingest", prefix: str | None = None) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{prefix or logger_name}_{run_ts}.log"

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return log_path


def run_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
