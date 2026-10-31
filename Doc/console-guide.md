# Operator console: user guide

Read-only. Nothing here changes the index, the manifest, the logs or any server. Start it with
`./run_console.py` (real data, localhost only) or `./run_console.py --demo` (synthetic data; use this for
screenshots and demos). Requirements: `Doc/step-9-requirements.md`; plan and status: `Doc/step-9-plan.md`.

## Status header (every page)
Console health, MCP server (:8200), Ollama, the last maintenance result and how fresh the index is. In demo mode
the MCP/Ollama probes are not run (`n/a (demo)`). "Index STALE" means the last successful index step is older than
`stale_after_hours` (default 36) or the last maintenance run FAILED; runbook `Doc/Runbooks/stale-index.md`.

## Page 1: Index health
**Files.** *Files seen* is everything in the manifest. *Attempted* excludes files the rules skip on purpose
(excluded types, editor backups, lock files). *Indexed* = `extracted` + `ocr_extracted` + `ocr_low_confidence`
(the last group is indexed but flagged: OCR confidence between the 40.0 failure threshold and the high
threshold). *Failed* = status `failed`. *Needs attention* = `encrypted`, `empty`, `warning_empty_conversion`.
Percentages are of *attempted* files, so they differ from "failed / files seen".

**Chunks.** Chunk count and embedding status (`embedded`, `pending`). `pending` after a maintenance run means the
index step did not finish.

**Maintenance.** The last run and the eight most recent. The result of a run comes only from its own
`=== maintenance run end:` line; an old FAILED followed by an OK run shows OK. Columns `+ / ~ / −` are files added,
changed, removed.

**Search scale.** Chunks against the size where dense (vector) search needs an ANN index (default 200,000;
HYR-02). Colours: green below 50 %, amber from 50 %, red from 100 %. The runbook is `Doc/Runbooks/ann-index-needed.md`.

**Files by type.** Per extension, stacked by outcome (green indexed, red failed, amber needs attention, grey
skipped). The numbers are always printed next to the bar. The twelve biggest types are listed, the rest are
combined as "(other types)".

**Why files did not index cleanly.** Counts by cause with the ticket that tracks it. *Show files* filters the table
below. Each cause id has a section in `Doc/Runbooks/index-failure-causes.md`.

**Problem files.** Filter by cause, type or part of the path; click a column header to sort; 25 rows per page.
Hover a row for the full error text. This includes the low-confidence-OCR files (FR-1.5) with their confidence.

## Page 2: Query explorer
Type a question and press Explore to see how retrieval reaches its ranking. Nothing is generated unless you tick
*Also generate an answer* (real data only; it uses the GPU like a normal answer). Explorer runs are **not** written to
the production query logs: they go to `logs/explorer/explore_YYYY-MM-DD.jsonl`, so the analytics page is not distorted.

**Relevance gate (top card).** The engine first checks the raw dense distances: at least *required hits* of the top
results must be closer than the *distance threshold*, otherwise production does not call the language model. The card
says passed or not passed, why, what production would do, and a what-if row (would the gate pass if it required 1, 2, 3…
hits). This is the view that explains a refusal like the earlier `min_hits=2` case: a single genuine match is
rejected if two are required.

**Three lists.** *Dense (meaning)*: the 20 nearest chunks by embedding distance (smaller is closer); a filled dot means
under the threshold. *Keyword (BM25)*: the 20 best word-match chunks (more negative is better). *Fused ranking (RRF)*:
the 8 chunks that would be given to the language model, in order, with which leg(s) found each ("both", "dense only",
"keyword only") and its rank and score in each leg. Green rows in the two leg lists are the ones that made the fused
list. Open *excerpt* to read the chunk text. The same file can appear several times: lists are per chunk, not per file.

**Timings.** Embedding, dense search, keyword search, fusion and total, in milliseconds (plus generation when asked).

**Demo mode** uses a toy embedder (hashed words, `console/demo_embed.py`) with its own threshold, so distances there
are not comparable with real ones; no language model is connected, so generation is unavailable.

**Limits.** One exploration at a time (a second gets a "busy" message); questions up to 1,000 characters.

## Page 4: Tool-call monitor
Answers: does the agent model really call `ask_documents`, how long does it take to start, and does the desktop see the
request? Data comes from the OpenClaw logs on the bot VM, copied into `logs/agent/` by `scripts/pull_agent_logs.sh`
(read-only; run it hourly from cron, because the VM clears /tmp when it reboots), and from the desktop's structured
query log (`caller` = `mcp`).

**Numbers.** *Agent turns*: distinct agent runs seen in the log. *Real tool-call rate*: turns where OpenClaw logged
`tool_execution_started`. *Tool call written as text*: the model printed a tool call instead of making it (OpenClaw
logs "looks like a tool call, but no structured tool invocation was emitted"; see the caveat below). *Seen by the
desktop*: tool starts paired with a desktop MCP request that began within 20 s of it; a start without a request means
the call never reached the MCP server. *Time to tool*: from the message arriving until the tool starts (agent side;
retrieval is the desktop's own time).

**Needs a look** lists the events worth reading: MCP connect failures (sessions started then have no tool until `/new`),
a tool started but never seen by the desktop, a tool removed by policy, text-instead-of-call turns, the VM being frozen,
Ollama preflight failures. **By agent model** compares models (rate, text calls, time to tool). **By day** puts the agent
side next to the desktop side; a red row has a failure to look at.

**Caveats.** (1) The "written as text" line has not yet been seen in a real log; the detection uses the message
documented in `Doc/step-5-requirements.md`, and a turn with no tool start is always visible in the rate. (2) Before the
structured query log existed (before 2026-10-31) the desktop side cannot tell MCP from other callers, so a tool start is
confirmed by any query logged at that time and is not counted as an MCP request. (3) The `dev` OpenClaw instance's logs
are ignored. Runbooks: `Doc/Runbooks/tool-never-called.md`, `Doc/Runbooks/mcp-server-down.md`.

## Page 3: Query analytics
What people ask, how long answers take and how often the assistant finds nothing relevant. Data: the query logs in `logs/`
(`query_DATE.jsonl` where it exists, plus the text log `query_DATE.log` for anything before the first JSONL record of a day,
so days from before the structured log, and a day on which the server was restarted, are still complete). Pick a period at
the top right (last 7, 14, 30 or 90 days, counting today).

**Numbers (all exclude automatic prompts):** a question starting with `### Task:` is an Open WebUI housekeeping prompt
(chat title, follow-up suggestions). It is counted once as "automatic prompts" and left out of every rate, chart and list.

| Card | Meaning |
|---|---|
| Questions | user questions in the period, with the caller split (`mcp` = Signal/OpenClaw, `http` = Open WebUI, `cli`; text-only days have no caller) |
| Typical time | median total seconds of *answered and general-knowledge* questions, plus 95th percentile and slowest (errors are counted, not timed) |
| No relevant result | share of questions the relevance gate refused (nothing close enough and general knowledge is off). Use the Query explorer on one of them to see why |
| Errors | embedding or generation failed (Ollama down, timeout) |
| Slow | share of timed questions at or above the slow threshold (`slow_query_seconds` in the console config, default 30 s; the MCP timeout is 60 s) |
| Without sources | any question that ended with no source documents: refused, general knowledge or failed |

Charts: questions per day by outcome, and median / 95th percentile time per day with the slow line. Tabs list the slowest
questions, those with no relevant result and failed ones (newest or slowest first, 15 shown). "Recurring questions" groups
identical questions (ignoring case and a final `?`) asked at least twice, with common words below them.
`GET /api/v1/queries/stats?days=30&slow_seconds=20` can override the threshold for one request.

**Privacy mode** (`mask_queries: true`): question text, file names and path-like text in error messages become short codes
such as `[masked-3fa9c1d2]`. The same question always gets the same code, so recurrence stays visible; the common-words list
is hidden because words would reveal the text.

## API (for scripts)
Interactive docs at `/docs`; snapshot in `Doc/api/openapi.json`. Page 4 uses `GET /api/v1/toolcalls/summary?days=30`. Page 3 uses `GET /api/v1/queries/stats?days=30` and `GET /api/v1/queries/slow?kind=slow|no_result|error&days=30&limit=15`. Page 2 uses `POST /api/v1/explore` (body `{"query": "...", "generate": false}`). Page 1 uses `/api/v1/health`,
`/api/v1/index/summary`, `/api/v1/index/failures`, `/api/v1/index/causes`, `/api/v1/maintenance/runs`.

## Privacy
Set `mask_queries: true` in the console config to replace file names by short hashes (the extension is kept), to hide paths
inside error messages, and to replace chunk excerpts in the explorer by `[masked]`. The numbers stay the same. The explorer log
(`logs/explorer/`) contains the questions you typed: it is personal data like the production query logs.
