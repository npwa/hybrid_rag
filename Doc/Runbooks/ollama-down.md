# Runbook: Ollama is down or not answering

**Shown as:** status header "Ollama down"; Tool-call monitor flag "Ollama preflight failed"; Query analytics errors
("could not reach Ollama", timeouts); `scripts/triage.sh 6`.

## What it means
Everything on the desktop needs Ollama (:11434): embedding of every question (`nomic-embed-text`), generation of the answer, and the
VM's agent model `qwen3.6:35b-a3b` too. When it is down, questions fail at the embedding step ("embedding failed"), and the agent
cannot think at all.

## Check
- `curl -s localhost:11434/api/tags | head -c 200`; `systemctl status ollama`.
- `scripts/triage.sh 6` (Ollama answering, embedding model present).
- `ollama ps`: which models are loaded. The first call after idle reloads the model and can take tens of seconds; the agent model and
  the embedding model compete for memory.
- A preflight failure that coincides with a "VM was frozen" flag is the VM waking from suspend; it usually recovers by itself.

## Fix
- Start or restart the service (`systemctl restart ollama`), then `ollama pull nomic-embed-text` if the model is missing.
- Re-run the question; nothing needs re-indexing for a query-time failure.
