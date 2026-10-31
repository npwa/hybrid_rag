# PM-04: Small models could not make structured tool calls

**Date:** 2026-09-06. **Severity:** Medium (design constraint, no data impact).

## Summary
Every 8 to 14B model tried as the OpenClaw agent model (`mistral:latest`, `qwen2.5:14b-instruct`, `llama3.1:8b`) failed to use
`ask_documents`, although Ollama marked them as tool-capable.

## Impact
No working Signal path until a larger model was chosen. The chosen `qwen3.6:35b-a3b` is slow: a real question on 2026-10-31 took
2 min 40 s (about 72 s before the tool call, 17 s on the desktop, about 80 s to write the reply).

## Timeline
- Three failure modes seen across the small models: declining, printing the tool call as plain text, answering an unrelated
  stale question.
- Reproduced with plain `curl` against Ollama, bypassing OpenClaw.
- `qwen3.6:35b-a3b` (mixture of experts, spills to CPU) passed all tests, also with a realistic multi-tool prompt, and became the default.
- A `qwen3:8b` speed experiment was tried and reverted (`step-5-requirements.md` §5a).

## Detection
Real Signal use. OpenClaw logs "Assistant reply looks like a tool call, but no structured tool invocation was emitted" for the
text-printing case.

## Root cause
Model capability, not configuration: OpenClaw's own documentation says models below about 14B struggle with multi-step tool calling.

## Fix
Use a 30B-class model as `agents.defaults.model.primary`.

## Prevention
- Tool-call monitor: tool-call rate per model, count of "written as text" turns and time to tool, by day. A model change shows up
  as a change in those numbers.
- The exact log line is only known from documentation; capturing a real one is open question 9 in `step-9-requirements.md`.
- Trade-off to revisit: speed. A faster model must keep the tool-call rate near 100% on the gold set before it replaces the current one.
