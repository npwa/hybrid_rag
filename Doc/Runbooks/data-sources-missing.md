# Runbook: a data source is missing

**Shown as:** `scripts/triage.sh 10` "data sources: missing …"; a 503 `source_unavailable` from the API; empty pages with a "not found" message.

## What it means
The console reads the manifest (`manifest.db`), the vector index (`lancedb/`), `logs/maintenance.log`, the query logs and `logs/agent/`.
The health endpoint (`/api/v1/health`) lists each source with its path and whether it is present and read-only.

## Check
- Open `/api/v1/health` (or the status header) and look for `present: false`.
- Config: `working_dir` and the relative paths in `config/console_config.yaml`; demo mode (`--demo`) looks at `demo_data/` instead.
- The index files are written by the maintenance run; they should exist wherever it runs.

## Fix
- Correct the path in the console config and restart the console.
- A missing `query_*.jsonl` for today only means no question has been asked since the engine started; it needs the MCP server to run the
  current code (restart `run_mcp_server.py`, `scripts/triage.sh 1`).
