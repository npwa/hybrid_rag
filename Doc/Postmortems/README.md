# Postmortems

Blameless write-ups of real incidents in this project: what happened, why, and what stops it happening again. Facts come
from `Doc/step-5-requirements.md`, the Issues in `Doc/Issues/` and git history; where a time or number was not recorded,
the text says so instead of guessing. Format: summary, impact, timeline, detection, root cause, fix, prevention.

| # | Incident | Where it showed up | Runbook |
|---|---|---|---|
| 1 | [Valid single-source answer refused by the relevance gate](PM-01-min-hits-refusal.md) | Signal, Open WebUI | `Doc/Runbooks/no-relevant-result.md` |
| 2 | [Tool invisible to the OpenClaw agent](PM-02-tool-not-visible.md) | Signal | `Doc/Runbooks/tool-never-called.md` |
| 3 | [Privacy refusal that came from OpenClaw's own workspace files](PM-03-workspace-file-directives.md) | Signal | `Doc/Runbooks/tool-never-called.md` |
| 4 | [Small models cannot make structured tool calls](PM-04-small-model-tool-calls.md) | Signal | `Doc/Runbooks/tool-never-called.md` |
| 5 | [Tool missing because the MCP server was down at session start](PM-05-mcp-server-down.md) | Signal | `Doc/Runbooks/mcp-server-down.md` |
| 6 | [NFS "permission denied" after uid mapping changes](PM-06-nfs-permission-denied.md) | maintenance / ingest | `Doc/Runbooks/index-failure-causes.md` |

The common thread of 1 to 4: they were found only by real questions arriving through Signal, never by the CLI tests. That is
what the console's Query explorer, Tool-call monitor and the gold question set (`scripts/run_gold_set.py`) are for.
