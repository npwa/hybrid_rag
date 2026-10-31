# PM-03: Refusals caused by OpenClaw's own workspace files

**Date:** 2026-09-06 to 2026-09-08. **Severity:** Medium (wrong behaviour on legitimate questions).

## Summary
The agent declined a question about the user's own account number, and later skipped `ask_documents` for "last flew to Palo Alto".
In both cases the cause was an instruction in a file of OpenClaw's workspace, not the project's tool description.

## Impact
Questions about personal facts were refused or answered from the wrong tool (`memory_search`). Number of affected questions not recorded.

## Timeline
- "United Mileage plus account number?" was refused as sensitive. Adding reassurance to the MCP server instructions and tool docstring
  was not enough.
- Testing the real, unedited `SOUL.md`/`AGENTS.md`/`USER.md` against Ollama reproduced the refusal. `SOUL.md` said "Private things stay
  private. Period."
- Fix: clarified `SOUL.md` and added a note for `hybrid-rag__ask_documents` to `AGENTS.md`.
- Later "Seriously, when did I last fly to Palo Alto?" called `memory_search` and never reached the tool (no `QUERY` line on the desktop).
  `MEMORY.md` said to call `memory_search` before answering any question about past conversations. Reproduced 4 of 5 times.
- Fix: one carve-out line in `MEMORY.md`; validated 6/6 on the failing case and `memory_search` still fires for a genuine
  question about the conversation.

## Detection
By a person, then by comparing Signal history with the desktop query log: a question asked and nothing logged on the desktop.

## Root cause
Workspace files each carried a directive that was correct for its original purpose and conflicted with the new tool once it was added.
Their combination with the longer real system prompt mattered; short test prompts did not reproduce it.

## Fix
As above (workspace files edited at the source).

## Prevention
- When the model does not call the tool, grep the whole live workspace for `memory`, `private`, `personal` and the tool's name
  before editing the tool description (runbook `tool-never-called.md`).
- The Tool-call monitor shows turns with no tool start and the desktop-side request count side by side, which makes "asked, never
  logged" visible without reading logs.
- Workspace copies in `openclaw-workspace/` are kept out of git on purpose (personal content).
