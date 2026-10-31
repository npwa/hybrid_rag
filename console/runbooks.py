"""Every warning the console can show, with the runbook that explains it (FR-X.2, DOC2). The API attaches these to
health warnings and tool-call flags; tests check that each file exists (T-DOC-1)."""
from __future__ import annotations

RUNBOOK_DIR = "Doc/Runbooks"

# warning id -> (what the user sees, runbook file)
WARNINGS: dict[str, tuple[str, str]] = {
    "api_unreachable": ("The console API cannot be reached", "console-down.md"),
    "mcp_down": ("MCP server is down", "mcp-server-down.md"),
    "ollama_down": ("Ollama is down", "ollama-down.md"),
    "index_stale": ("The index looks stale", "stale-index.md"),
    "maintenance_failed": ("The last maintenance run failed", "stale-index.md"),
    "source_missing": ("A data source is missing", "data-sources-missing.md"),
    "ann_index_needed": ("The vector index needs an ANN index", "ann-index-needed.md"),
    "problem_files": ("Files failed to index", "index-failure-causes.md"),
    "mcp_connect_failure": ("MCP connect failure", "mcp-server-down.md"),
    "tool_start_without_desktop_call": ("Tool started, desktop saw nothing", "mcp-server-down.md"),
    "tool_removed_by_policy": ("Tool removed by policy", "tool-never-called.md"),
    "looks_like_tool_call": ("Tool call written as text", "tool-never-called.md"),
    "agent_failed": ("Agent failed before reply", "tool-never-called.md"),
    "tool_slow": ("Slow time to tool", "slow-answers.md"),
    "slow_answers": ("Slow answers", "slow-answers.md"),
    "host_gap": ("VM was frozen", "vm-frozen-or-rebooted.md"),
    "provider_preflight_failed": ("Ollama preflight failed", "ollama-down.md"),
    "query_errors": ("Questions failed with an error", "ollama-down.md"),
    "no_relevant_result": ("Questions with no relevant result", "no-relevant-result.md"),
    "agent_logs_stale": ("Agent log copies are old", "agent-logs-stale.md"),
    "agent_logs_missing": ("No agent logs copied yet", "agent-logs-stale.md"),
}


def runbook_path(warning_id: str) -> str | None:
    w = WARNINGS.get(warning_id)
    return f"{RUNBOOK_DIR}/{w[1]}" if w else None


def listing() -> list[dict]:
    return [{"id": k, "title": t, "runbook": f"{RUNBOOK_DIR}/{f}"} for k, (t, f) in WARNINGS.items()]
