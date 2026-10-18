"""One growing log per day — step-5-requirements.md §6. Unlike Steps 1/3/4's one-log-
per-run (batch jobs with a clear start/end), this is a long-running service, so the log
rotates by calendar day instead."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


class _DailyFileHandler(logging.Handler):
    """Writes to logs/query_<today>.log, actually re-checking "today" on every record
    instead of only once.

    Bug this replaces: a plain FileHandler's target path is computed once, when
    setup_query_logging() is called — fine for the CLI (one process per invocation,
    so "today" never changes mid-run), but wrong for the two long-running servers that
    call this (run_mcp_server.py, run_server.py). A server started on day N and never
    restarted kept writing every query into query_<N>.log forever, silently never
    rotating — discovered when a real Signal query's log entry was "missing," only to
    turn up, correctly grounded and accurate, filed under a server-startup date over a
    month old."""

    def __init__(self, logs_dir: Path, fmt: logging.Formatter):
        super().__init__()
        self.logs_dir = logs_dir
        self.setFormatter(fmt)
        self._day: date | None = None
        self._file_handler: logging.FileHandler | None = None

    def _path_for(self, day: date) -> Path:
        return self.logs_dir / f"query_{day.isoformat()}.log"

    def _ensure_current(self) -> None:
        today = date.today()
        if today != self._day:
            if self._file_handler is not None:
                self._file_handler.close()
            self._file_handler = logging.FileHandler(self._path_for(today), encoding="utf-8")
            self._file_handler.setFormatter(self.formatter)
            self._day = today

    def emit(self, record: logging.LogRecord) -> None:
        self._ensure_current()
        self._file_handler.emit(record)

    def close(self) -> None:
        if self._file_handler is not None:
            self._file_handler.close()
        super().close()

    @property
    def current_path(self) -> Path:
        self._ensure_current()
        return self._path_for(self._day)


def setup_query_logging(logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("query")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        fh = _DailyFileHandler(logs_dir, fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
        return fh.current_path

    # Already configured (a second call in the same process) — report whichever
    # handler is the daily one, falling back to today's expected path if something
    # else configured the logger first.
    for h in logger.handlers:
        if isinstance(h, _DailyFileHandler):
            return h.current_path
    return logs_dir / f"query_{date.today().isoformat()}.log"
