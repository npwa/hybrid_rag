# Runbook: "VM was frozen" in the Tool-call monitor

**Shown as:** flag "VM was frozen" with a duration, often together with "Ollama preflight failed" or an MCP connect failure.

## What it means
OpenClaw logged a "host timing gap": its process did not run for the stated time (suspend, hibernate, host sleep, a paused VM). Replies
cannot arrive during the gap, and a session started right after may have run its first checks while the desktop's services were still waking.

## Check
- Was the desktop or the VM suspended? `journalctl --since yesterday | grep -i suspend`; `virsh domstate npa-u24`.
- Was the MCP server up when the session began? Compare with the "MCP connect failure" flags (`mcp-server-down.md`).
- The VM also reboots daily at about 21:52 (cause unknown, HYR-10 item 3): a gap at that hour is that reboot.

## Fix
Nothing to repair for a single gap. If a session lacks the tool afterwards, send `/new` in Signal. Prevent repeats by finding what suspends
the host or VM (and, for the daily reboot, why it happens).
