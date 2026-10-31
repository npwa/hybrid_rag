# PM-02: The tool was invisible to the OpenClaw agent

**Date:** 2026-09-06 (Step 5 integration). **Severity:** Medium (feature unusable, no wrong answers).

## Summary
`ask_documents` worked from the MCP client but the agent behind Signal never offered it, with no error shown to the user.

## Impact
No Signal question could reach the documents until fixed.

## Timeline
- MCP server verified with the official `mcp` client: `list_tools()` and `call_tool()` fine, also over the LAN IP.
- OpenClaw configured with the tool in `tools.allow` only. The agent did not see it.
- Added `tools.sandbox.tools.alsoAllow` as well; the tool appeared.

## Detection
A real Signal round trip. A protocol-level test cannot see the agent's own tool filtering.

## Root cause
With `agents.defaults.sandbox.mode` set to `"non-main"`, OpenClaw needs the tool in two places: `tools.allow` and the separate
`tools.sandbox.tools.alsoAllow`. Missing the second drops the tool silently. `agents.defaults.sandbox` configures sandbox
mode, not this list, which made it easy to look in the wrong place.

## Fix
Both settings contain `hybrid-rag__ask_documents`.

## Prevention
- `scripts/vm/openclaw-config-summary` (cron on the VM) writes `config-summary.json`; `triage.sh` and the Tool-call monitor
  read `tools_allow_has_tool` and `sandbox_alsoAllow_has_tool` and flag a missing one.
- The log line "tool removed by policy" is a flag on the Tool-call monitor.
