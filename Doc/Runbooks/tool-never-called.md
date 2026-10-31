# Runbook: the agent does not call the tool (or calls it too slowly)

**Shown as:** on the Tool-call monitor page a low "real tool-call rate", "Tool call written as text", a model with
many turns but few tool starts, a slow time to tool, or `scripts/triage.sh 3`. **Related:** `Doc/step-5-requirements.md`
§5c-5j on branch `alternate` (model evaluation), SOUL.md/MEMORY.md finding.

## What it means
The Signal answer is produced by the OpenClaw agent model, which must emit a *structured* tool call to
`hybrid-rag__ask_documents`. Small models often print the call as text instead ("looks like a tool call, but no
structured tool invocation was emitted"); the user then sees JSON or a made-up answer and the desktop sees nothing.
A slow *time to tool* (message arrival until the tool starts) is the agent side: model loading, a large session, long
workspace files. It is not retrieval (the desktop's own time is the "Desktop MCP requests" line).

## Check
1. Tool-call monitor page: look at the model row (rate and "written as text") and the by-day table.
2. `scripts/triage.sh 3`: is `agents.defaults.model.primary` the model you expect (`ollama/qwen3.6:35b-a3b` works)?
3. Is the tool allowed in both places? The summary shows `tools.allow` and `sandbox alsoAllow` (triage menu 1).
4. A session older than the model/tool change keeps the old setup: send `/new` in Signal.
5. Slow starts only: is Ollama loading the model (`ollama ps` on the desktop, first call after idle)?

## Fix
- Wrong/small model: set a model known to work (see the model table; changing it is a change on the VM, not done by the console).
- Tool missing from a session: `/new`; then `scripts/triage.sh 1`.
- Workspace files overriding the tool (SOUL.md, MEMORY.md): trim them (Doc/step-5-requirements.md).
- Slow starts: keep the model warm, shorten the session (`/new`), reduce workspace file size.
