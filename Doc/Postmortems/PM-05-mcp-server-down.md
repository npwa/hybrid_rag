# PM-05: The tool was missing because the MCP server was down at session start

**Date:** late October 2026 (exact time not recorded; found while debugging "Signal cannot find `hybrid-rag__ask_documents`").
**Severity:** Medium.

## Summary
Signal replied that it had no `hybrid-rag__ask_documents` tool. The configuration was correct; the MCP server on the desktop was
not running when the agent's session started, so the session never received the tool.

## Impact
Signal questions could not reach the documents until the server was started and a new session opened with `/new`.

## Timeline
(Reconstructed from the diagnosis; no timestamps were kept.)
- OpenClaw session starts, tries to connect to `http://<desktop>:8200/mcp`, fails ("MCP: failed to start server").
- The session continues without the tool; later the server is up again but the session does not retry.
- Diagnosis led to `scripts/triage.sh` (menu 1) and its checks: server listening, the desktop IP in OpenClaw's URL matches the
  desktop's current address, connect failures in today's agent log.
- Server started, `/new` sent, tool worked.

## Detection
By a person from the Signal reply. `triage.sh` was written from this incident.

## Root cause
No supervisor starts `run_mcp_server.py` (HYR-01), so it is down after a reboot or when its shell is closed, and OpenClaw only connects
at session start. A second contributor, the desktop's address changing, is why `triage.sh` compares IPs.

## Fix
Start the server (`triage.sh` offers to) and `/new`.

## Prevention
- HYR-01: systemd `--user` unit for the server (milestone M7).
- Tool-call monitor: "MCP connect failure" and "tool started, desktop saw nothing" flags, per day.
- Status header shows the MCP port state; `triage.sh` C-checks are in the runbook `mcp-server-down.md`.
