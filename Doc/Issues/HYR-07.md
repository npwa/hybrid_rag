# HYR-07: Open WebUI HTTP server (`run_server.py`, port 8100) not running

- **Severity:** Low
- **Status:** Open (only matters if the Open WebUI path is used)
- **Component:** `run_server.py`

## Impact
Nothing listens on :8100, so the Open WebUI integration is unavailable. The
Signal/MCP path (:8200) and the CLI (`run_query.py`) are unaffected.

## Description
Like the MCP server (HYR-01), the HTTP server is started manually and has no
supervisor. It is unclear whether the Open WebUI path is still wanted, since
Signal is the primary interface.

## Proposed fix
Decide whether to keep it. If yes, add a second `systemd --user` unit alongside
HYR-01 and a check in `scripts/triage.sh`. If no, note it as optional in the
README.

## Acceptance
A documented decision, plus a running service or an updated README.
