"""Status header / health data (FR-X.1). Shared meaning of 'up' for the console and scripts/triage.sh."""
from __future__ import annotations

import socket
import urllib.request
from datetime import datetime
from pathlib import Path

from console import __version__
from console.config import ConsoleConfig
from console.readers import maintenance_log
from console.runbooks import runbook_path
from console.readers.lance_reader import LanceReadOnly
from console.readers.sqlite_ro import is_read_only, open_ro


def _tcp_listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def _source(name: str, path: Path, read_only: bool | None, enforced_by: str, note: str | None = None) -> dict:
    return {"name": name, "path": str(path), "present": path.exists(), "read_only": read_only,
            "enforced_by": enforced_by, "note": note}


def build_health(config: ConsoleConfig, now: datetime | None = None) -> dict:
    now = now or config.now()
    sources = []

    ro = None
    if config.manifest_db.exists():
        try:
            conn = open_ro(config.manifest_db)
            ro = is_read_only(conn)
            conn.close()
        except Exception as e:                       # unreadable / corrupt: report, never raise
            sources.append(_source("manifest", config.manifest_db, None, "mode=ro + query_only", f"cannot open: {e}"))
    if not any(s["name"] == "manifest" for s in sources):
        sources.append(_source("manifest", config.manifest_db, ro, "mode=ro + query_only"))

    chunks = None
    if config.lancedb_dir.exists():
        try:
            chunks = LanceReadOnly(config.lancedb_dir, config.lancedb_table).count_rows()
            sources.append(_source("lancedb", config.lancedb_dir, True, "wrapper without write methods"))
        except Exception as e:
            sources.append(_source("lancedb", config.lancedb_dir, None, "wrapper without write methods", f"cannot open: {e}"))
    else:
        sources.append(_source("lancedb", config.lancedb_dir, None, "wrapper without write methods"))

    mlog = config.logs_dir / "maintenance.log"
    sources.append(_source("maintenance_log", mlog, True, "opened for reading only"))
    today = now.date().isoformat()
    for fmt in ("log", "jsonl"):
        p = config.logs_dir / f"query_{today}.{fmt}"
        sources.append(_source(f"query_{fmt}_today", p, True, "opened for reading only",
                               None if p.exists() else "none yet today" if fmt == "jsonl" else None))
    sources.append(_source("agent_logs", config.agent_logs_dir, True, "opened for reading only"))

    runs = maintenance_log.read_runs(mlog)
    last = maintenance_log.last_run(runs)
    idx_at = maintenance_log.last_successful_index(runs)
    age = maintenance_log.hours_since(idx_at, now)
    stale = (age is None) or age > config.stale_after_hours or (last is not None and last.result == "FAILED")

    if config.demo:
        services = {"mcp_server": {"state": "n/a (demo)"}, "ollama": {"state": "n/a (demo)"}}
    else:
        services = {
            "mcp_server": {"state": "up" if _tcp_listening(config.mcp_port) else "down", "port": config.mcp_port},
            "ollama": {"state": "up" if _http_ok(f"{config.ollama_url}/api/tags") else "down", "url": config.ollama_url},
        }

    problems = [s["name"] for s in sources if s["name"] in ("manifest", "lancedb") and not s["present"]]
    warnings = []

    def warn(wid: str, text: str):
        warnings.append({"id": wid, "text": text, "runbook": runbook_path(wid)})
    if services["mcp_server"]["state"] == "down":
        warn("mcp_down", f"The MCP server is not listening on :{config.mcp_port}; Signal cannot reach the documents.")
    if services["ollama"]["state"] == "down":
        warn("ollama_down", f"Ollama does not answer at {config.ollama_url}; questions cannot be embedded or answered.")
    if last is not None and last.result == "FAILED":
        warn("maintenance_failed", "The last maintenance run failed.")
    elif stale:
        warn("index_stale", "The last successful index step is older than the limit; new documents may be missing.")
    for s in sources:
        if s["name"] in ("manifest", "lancedb", "maintenance_log") and not s["present"]:
            warn("source_missing", f"{s['name']} not found at {s['path']}.")
    return {
        "status": "ok" if not problems else "degraded",
        "version": __version__,
        "demo": config.demo,
        "time": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": sources,
        "warnings": warnings,
        "services": services,
        "maintenance": {
            "last_run": None if last is None else {
                "started": last.started, "ended": last.ended, "result": last.result, "seconds": last.seconds,
                "added": last.added, "changed": last.changed, "removed": last.removed},
            "last_successful_index": idx_at,
            "index_age_hours": None if age is None else round(age, 1),
            "stale_after_hours": config.stale_after_hours,
            "stale": stale,
        },
        "index": {"chunks": chunks, "ann_threshold_chunks": config.ann_threshold_chunks},
    }
