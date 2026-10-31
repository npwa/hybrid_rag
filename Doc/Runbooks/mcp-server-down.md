# Runbook: the MCP server was down (tool missing or started but never arrived)

**Shown as:** Tool-call monitor flags "MCP connect failure" and "Tool started, desktop saw nothing"; status header
"MCP server down"; Signal replies that it cannot find `hybrid-rag__ask_documents`. **Ticket:** HYR-01 (no service
supervisor yet; planned for milestone M7).

## What it means
OpenClaw connects to the desktop's MCP server (`run_mcp_server.py`, :8200) when a session starts. If the server is
down then, the session never gets the tool, and it stays missing until `/new`. If it goes down *after* the session
started, the agent starts the tool but the desktop never logs a request.

## Check
- `scripts/triage.sh 1` (server listening? desktop IP matches the URL OpenClaw uses? connect failures today?).
- `ss -ltn | grep 8200`; `tail logs/run_stdout.log`.
- Did the desktop reboot? (no unit starts the server yet).

## Fix
1. Start it with the project's Python: `nohup .venv/bin/python run_mcp_server.py >> logs/run_stdout.log 2>&1 &`
   (or accept the offer in `scripts/triage.sh 1`).
2. In Signal send `/new` so the next session sees the tool.
3. Confirm: `scripts/triage.sh -y` has no FAIL; a test question shows a matching request on this page.

## Prevent
The systemd `--user` unit (HYR-01) will start it at boot; until then check after every reboot.
