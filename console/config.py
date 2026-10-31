"""Load the console config (config/console_config.yaml). Every path is resolved against
working_dir; demo mode swaps in the synthetic dataset so nothing real is touched."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclasses.dataclass
class ConsoleConfig:
    working_dir: Path
    manifest_db: Path
    lancedb_dir: Path
    lancedb_table: str
    logs_dir: Path          # maintenance.log, query_*.log (and query_*.jsonl)
    agent_logs_dir: Path    # local copies of OpenClaw logs (scripts/pull_agent_logs.sh)
    host: str
    port: int
    stale_after_hours: float
    slow_query_seconds: float
    ann_threshold_chunks: int
    mask_queries: bool      # redact query text and file paths in API/UI (FR-3.6, P3)
    mcp_port: int           # MCP server port probed by the status header
    ollama_url: str
    static_dir: Path        # built web UI (console/web/dist), relative to the project root
    demo: bool

    @classmethod
    def load(cls, path: str | Path, demo: bool = False, working_dir: str | Path | None = None) -> "ConsoleConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        if working_dir is not None:
            raw["working_dir"] = str(working_dir)
        elif demo:
            raw["working_dir"] = raw.get("demo_dir", "demo_data")
            raw["mask_queries"] = False   # synthetic data: nothing to hide
        wd = Path(raw.get("working_dir", ".")).expanduser().resolve()

        def rel(key: str, default: str) -> Path:
            p = Path(raw.get(key, default)).expanduser()
            return p if p.is_absolute() else (wd / p)

        return cls(
            working_dir=wd,
            manifest_db=rel("manifest_db", "manifest.db"),
            lancedb_dir=rel("lancedb_dir", "lancedb"),
            lancedb_table=raw.get("lancedb_table", "chunks"),
            logs_dir=rel("logs_dir", "logs"),
            agent_logs_dir=rel("agent_logs_dir", "logs/agent"),
            host=raw.get("host", "127.0.0.1"),
            port=int(raw.get("port", 8300)),
            stale_after_hours=float(raw.get("stale_after_hours", 36)),
            slow_query_seconds=float(raw.get("slow_query_seconds", 30)),
            ann_threshold_chunks=int(raw.get("ann_threshold_chunks", 200_000)),
            mask_queries=bool(raw.get("mask_queries", False)),
            mcp_port=int(raw.get("mcp_port", 8200)),
            ollama_url=str(raw.get("ollama_url", "http://localhost:11434")).rstrip("/"),
            static_dir=Path(raw.get("static_dir", PROJECT_ROOT / "console" / "web" / "dist")),
            demo=demo,
        )
