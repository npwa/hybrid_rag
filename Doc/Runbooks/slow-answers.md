# Runbook: answers are slow or time out

**Shown as:** Query analytics "Slow" rate and the "Slowest" tab; Tool-call monitor "Time to tool"; Signal "request timed out after 60 s"; `scripts/triage.sh 4`.

## What it means
The time of a Signal answer has three parts, and the console shows each one:
1. **Before the tool** (Tool-call monitor, "Time to tool"): the agent model on the VM thinking. 50 to 70 s is normal for `qwen3.6:35b-a3b`.
2. **The desktop** (Query analytics, "Typical time"; "Desktop MCP requests"): embedding, retrieval and generation. Seconds, or 15 to 20 s
   if Ollama had to reload a model.
3. **After the tool**: the agent model composing the reply (about 80 s on 2026-10-31); not visible on the desktop.
The MCP tool call itself times out at 60 s.

## Check
- Which part is slow? Compare the three numbers for the slow question. Only part 2 is retrieval; parts 1 and 3 are the agent model.
- `ollama ps`: are both the embedding model and the big model loaded, or do they swap?
- Long sessions slow the agent: send `/new`.

## Fix
- Part 2: keep models loaded (`OLLAMA_KEEP_ALIVE`), check GPU memory, reduce `top_k_fused` only after the gold set confirms no loss.
- Parts 1 and 3: shorter workspace files, `/new`, or a faster model that still keeps the tool-call rate near 100% (`tool-never-called.md`).
