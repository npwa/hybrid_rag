"""One growing log per day — step-5-requirements.md §6. Unlike Steps 1/3/4's one-log-
per-run (batch jobs with a clear start/end), this is a long-running service, so the log
rotates by calendar day instead."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


def setup_query_logging(logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"query_{date.today().isoformat()}.log"

    logger = logging.getLogger("query")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return log_path
