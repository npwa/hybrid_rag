# Runbook: agent log copies are old, or the VM log cannot be read

**Shown as:** Tool-call monitor banner "The newest copied log is … old"; "No OpenClaw logs found"; `scripts/triage.sh` C6 or
"cannot read today's OpenClaw log"; `scripts/pull_agent_logs.sh` prints "Permission denied". **Ticket:** HYR-10.

## What it means
The OpenClaw logs live in `/tmp/openclaw` on the VM and are copied to `logs/agent/` by `scripts/pull_agent_logs.sh` as the read-only user
`ragr`. The VM clears `/tmp` at each reboot (about 21:52 daily) and OpenClaw sometimes resets file modes, so access is lost until the
VM-side cron job (`*/5`, user `nick`) restores the ACLs.

## Check
- `scripts/pull_agent_logs.sh -n` (dry run) and `ssh ragr@npabot-u24 ls -l /tmp/openclaw`.
- A directory showing `drwx------` without a `+` lost its ACL (reboot). A file showing `-rw-------+` has a zero ACL mask. Both are repaired
  by the cron job within 5 minutes; see HYR-10 for the three `setfacl` commands to run by hand as `nick`.
- VM unreachable: `scripts/triage.sh 2` and `virsh list` (a VM that is "running" but unresponsive was seen after host suspend).

## Fix
- Wait for the cron job or run the HYR-10 commands, then `scripts/pull_agent_logs.sh`.
- Pull regularly so a reboot loses at most an hour: `7 * * * * /home/npalmass/work/hybrid_rag/scripts/pull_agent_logs.sh -q`.
