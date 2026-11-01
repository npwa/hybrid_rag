# HYR-01: MCP server has no service supervisor (manual start only)

- **Severity:** High
- **Status:** Fixed in code on branch `console` (2026-11-01); installed and enabled by the owner (2026-11-01, lingering on); acceptance (reboot test) pending
- **Component:** `run_mcp_server.py` (desktop npalmass-desk1, port 8200)

## Impact
After a desktop reboot or crash the MCP server stays down. OpenClaw sessions that
start in that window never get the `hybrid-rag__ask_documents` tool, and Signal
replies "can't find the tool" until the server is started and `/new` is sent.
This is the only failure that has hit the live Signal path so far.

## Description
The server is started by hand (`./run_mcp_server.py`). Nothing starts it at boot,
restarts it on failure, or orders it before the OpenClaw VM (`npabot-u24`).
`scripts/triage.sh` can detect and start it, but only when someone runs it.

## Proposed fix
Add a `systemd --user` unit (`hybrid-rag-mcp.service`) with `Restart=on-failure`,
the project venv/working directory, and `loginctl enable-linger` so it runs
without a login session. Document install steps in the README, and update the
triage.sh `start_mcp` fix to use `systemctl --user start` when the unit exists.

## Acceptance
Reboot the desktop; with no manual action, port 8200 listens and a fresh Signal
session can call `ask_documents`.

## Resolution (2026-11-01)
`deploy/systemd/hybrid-rag-mcp.service` (`Restart=on-failure`, project venv and working directory, ordered after the network and Ollama) and
`hybrid-rag-console.service`, installed by `scripts/install_services.sh` (see `Doc/console-guide.md`, "Running it as a service").
`scripts/triage.sh` reports the unit state and starts the MCP server through `systemctl --user start` when the unit is installed. Lingering is
not enabled by the script (it changes the login-manager state); the installer prints the command. **Not yet verified by a real desktop reboot.**
