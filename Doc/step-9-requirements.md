# Step 9 Requirements: Operator Console (observability)

Draft for review. Derived from `Doc/improvements.md` (purpose and strategy). Adds a
read-only web console and a small read-only API over data the pipeline already produces.
Steps 1-8 (ingest through maintenance loop) are unchanged by this step.

---

## 1. Goals and non-goals

### Goals
- G1. Make the health of the pipeline visible without reading logs by hand.
- G2. Make retrieval behavior inspectable (why a chunk was or was not returned).
- G3. Surface recurring problems from the query logs and the agent tool-call path.
- G4. Turn the incidents already encountered into documented, linkable runbook and
  postmortem material.
- G5. Do all of the above without any risk to the working Signal/OpenClaw path.

### Non-goals (carried from `improvements.md`)
- NG1. No write actions from the console in v1 (no re-index, restart, or config edit).
  An approval queue for proposed fixes is a possible later step, not part of this one.
- NG2. No change to retrieval or generation behavior (thresholds, `min_hits`, prompts,
  models).
- NG3. No mock enterprise integrations (ServiceNow, Jira, identity) in v1.
- NG4. No multi-user features: no accounts, roles or sharing. Single operator, LAN only.

### Consistency constraint
Any README, slide, resume or interview text derived from this work states only what is
built. The project is Python plus (new) TypeScript/React; it does not demonstrate Go,
Java, ServiceNow or identity management, and must not imply it does.

## 2. Architecture constraints

- C1. **Separate process.** The console API runs as its own process (own port), not
  inside `run_server.py` or `run_mcp_server.py`. A bug or crash in the console must not
  affect the Signal path.
- C2. **Read-only data access.**
  - `manifest.db` opened with SQLite `mode=ro` (URI) and `query_only` set.
  - LanceDB opened read-only (no `add`/`delete`/index creation).
  - Log files opened for read only.
- C3. **No new datastore.** Aggregations are computed from existing sources (manifest,
  logs, index) on request or cached in memory. If caching to disk becomes necessary it
  goes under `logs/` or a clearly separate directory and is rebuildable.
- C4. **LAN-bound, no auth in v1**, but default bind is `127.0.0.1`; binding to the LAN
  is an explicit config option, with a warning in the README (the data is personal).
- C5. **Existing endpoints untouched.** `query/server.py` currently exposes only
  `/v1/models` and `/v1/chat/completions`; there is no dashboard-facing API, so the
  console API is new code (module `console/` or `api/`; naming to be decided).

## 3. Data sources (what exists today)

| Source | Location | Form | Notes |
|---|---|---|---|
| File/chunk state | `manifest.db` | SQLite: `files`, `chunks`, FTS5 | Statuses: extracted, ocr_extracted, ocr_low_confidence, failed, skipped, etc. |
| Failed-files report | `logs/failed_files_report.tsv`, `logs/manifest_export.jsonl` | TSV / JSONL | The TSV was a one-off; regeneration should be scripted (see FR-1.4). |
| Maintenance runs | `logs/maintenance.log` | Text, timestamped | Lines such as `=== maintenance run end: OK in 14s (+3 ~1 -0) ===`; `stage index: ok`. |
| Stage logs | `logs/{ingest,chunk,index}_*.log` | Text | Per-run detail. |
| Query log | `logs/query_YYYY-MM-DD.log` | Text lines | `QUERY '<q>' -> N sources, T s [...]`, `fusion detail: ... dense(rank,dist) sparse(rank,bm25)`, `generation: N tokens in T s`. |
| Vector index | `lancedb/` | LanceDB table | Dense search code in `query/dense.py`. |
| Agent tool calls | `/tmp/openclaw/openclaw-YYYY-MM-DD.log` on VM `npabot-u24`, read as user `ragr` | JSON lines (`gateway`, `agents/tool-policy`, `channels/signal`, ... subsystems) | **Not on the desktop.** Pulled over SSH (§7). Volatile (`/tmp`). Read access can lapse (HYR-10). A sample copy is `openclaw-2026-09-05.log` (untracked). |

Consequences:
- D1. Query and maintenance logs are free text. Parsing them is brittle; see FR-3.5 for
  the optional move to structured (JSONL) query logging.
- D2. Tool-call data lives on another machine. Page 4 needs an ingestion path (§7).

## 4. Functional requirements

### Page 1: Index health
- FR-1.1. Show file counts by type/extension and by manifest status, with totals and
  percent succeeded/failed (the same breakdown produced by hand during the earlier
  ingest analysis: total, failed, skipped, low-confidence).
- FR-1.2. Show the chunk count and the embedding status split (`pending`, `embedded`,
  `deleted`).
- FR-1.3. Show the last maintenance run: end time, result (OK/FAILED), duration, and
  `+added ~changed -removed`. The result must come from the **last** `maintenance run
  end` line only (the earlier triage.sh false-FAILED bug came from judging old lines).
- FR-1.4. List failed files with a cause category (permission denied, lock file, damaged
  file, no text/image-only, other), file path, extension, and a link to the matching
  ticket in `Doc/Issues/` where one exists. Table sortable and filterable.
- FR-1.5. List low-confidence-OCR files with their confidence score against the 40.0
  threshold.
- FR-1.6. Staleness indicator: warn when the last successful index is older than a
  configurable threshold (default 36 h given the daily cron) or when the last run was
  FAILED.
- FR-1.7. Show vector-index scale status: chunk count against the documented ~200k
  threshold at which dense search needs an ANN index (HYR-02).

### Page 2: Query explorer
- FR-2.1. Input a question; return, without generating an LLM answer by default:
  dense hits (rank, distance), BM25 hits (rank, score), fused RRF ranking, and for each
  chunk the source path and a text excerpt.
- FR-2.2. Show which leg(s) found each chunk (dense, sparse, both) and the RRF score,
  consistent with the "per-leg retrieval scores" already logged by the engine.
- FR-2.3. Show the active relevance settings (distance threshold, `min_hits`, top-k per
  leg, fused top-k) and mark which hits passed or failed each gate, so a refusal like the
  earlier `min_hits=2` case is explained.
- FR-2.4. Optional "also generate answer" toggle that runs the normal engine path and
  shows the answer plus timing (embed, retrieval, generation).
- FR-2.5. Explorer runs must not alter system state. They may be logged to a separate
  explorer log, never to the production `query_*.log`, so analytics (page 3) are not
  polluted.
- FR-2.6. Reuse the existing query engine/fusion/dense modules rather than
  reimplementing retrieval (so behavior matches production); exposing detail the engine
  already computes is allowed, changing its results is not (NG2).

### Page 3: Query log analytics
- FR-3.1. Time series over a selectable range: queries per day, median and p95 total
  latency, generation tokens/s.
- FR-3.2. Rates of: "no relevant result" answers, refusals, zero-source answers,
  slow queries (threshold configurable, default 30 s), timeouts/errors.
- FR-3.3. Table of the slowest queries and of queries with no relevant result, with the
  query text, timestamp and sources.
- FR-3.4. Top recurring queries/terms (simple counts) to support "recurring problems"
  review.
- FR-3.5. Parsing: the v1 parser handles the existing text format. Open question Q3 asks
  whether to add a JSONL sidecar log written by `query/logging_setup.py`; that would be a
  logging change only, with no effect on retrieval.
- FR-3.6. Query text is personal data: a config switch can mask query text in the UI and
  API (see §6).

### Page 4: Tool-call monitor
- FR-4.1. For OpenClaw sessions: count structured tool calls versus text that merely
  looks like a tool call (the case where the model emits JSON/prose instead of a call),
  and calls that were declined or filtered by tool policy.
- FR-4.2. Group by agent model (e.g. `ollama/qwen3.6:35b-a3b`) and by day.
- FR-4.3. Show MCP-side counts from the desktop (`ask_documents` invocations and
  latency) to compare against agent-side counts; a gap indicates the agent never reached
  the tool.
- FR-4.4. Highlight sessions started while the MCP server was down (tool missing from
  the allowed list), the failure behind HYR-01.
- FR-4.5. The exact log fields that identify "looks like a tool call" must be confirmed
  from real logs before this page is specified further (Q4). Until then the page is
  scoped to what the sample log supports.

- FR-4.6. Show time-to-tool (`totalMs` of `tool_execution_started`) per turn, median and p95;
  slow starts point at model load or a bloated session rather than at retrieval.

### Cross-cutting
- FR-X.1. A status header on every page: MCP server (:8200) listening, Ollama up,
  last maintenance result, index freshness. Mirrors the read-only checks in
  `scripts/triage.sh`.
- FR-X.2. Each warning links to a runbook entry (see §8).
- FR-X.3. All views work with a synthetic dataset (§6).

## 5. API requirements

Read-only HTTP+JSON, versioned under `/api/v1/`.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Status header data (FR-X.1) |
| `GET /api/v1/index/summary` | Counts by type/status, chunk split, last run, staleness |
| `GET /api/v1/index/failures` | Failed and low-confidence files, filterable |
| `GET /api/v1/maintenance/runs` | Run history from `maintenance.log` |
| `POST /api/v1/explore` | Retrieval detail for a question (FR-2.x); POST only because of the body, no side effects |
| `GET /api/v1/queries/stats` | Aggregates for page 3 |
| `GET /api/v1/queries/slow` | Slowest / no-result queries |
| `GET /api/v1/toolcalls/summary` | Page 4 aggregates |

- API1. Machine-readable schema (OpenAPI via FastAPI, which is already a dependency).
- API2. All endpoints idempotent and side-effect free. Pagination on list endpoints.
- API3. Response time target: under 1 s for pages 1 and 3 at the current corpus size
  (about 2,500 files, 18k chunks, tens of query-log files); the explorer is bounded by
  retrieval (about 0.1 s without generation).
- API4. Errors return a JSON body with a cause, not a stack trace.

## 6. Privacy and data handling

- P1. The indexed documents and query logs contain personal information (including
  account numbers). The console must not copy this data anywhere outside the machine.
- P2. **Demo mode:** a config option points the console at a synthetic dataset (a small
  manifest, index and set of logs generated by a script in `scripts/`) so screenshots,
  demos and any public repo contain no real data.
- P3. A masking option redacts query text and file paths in API responses and UI
  (FR-3.6).
- P4. No real data, logs or screenshots are committed. `.gitignore` covers console
  caches and build output (relates to HYR-08).

## 7. Tool-call data path (page 4)

**Decided: option A** (owner answer). The agent logs are on `npabot-u24` and are read as the
read-only user `ragr` (see HYR-09, HYR-10). Options considered:
- **A. Pull by SSH, read-only.** A script (using the existing read-only key approach from
  `scripts/triage.sh`) copies or tails the OpenClaw log to the desktop on demand or by
  cron. No changes on the VM.
- **B. Mounted/shared log path.** Requires a change on the VM or shares.
- **C. Desktop-side only.** Use MCP server logging alone (FR-4.3), dropping the agent
  side of page 4.

Chosen: A. It matches the read-only strategy. `scripts/triage.sh` already uses the same
access (`ragr`, plain read-only commands; optional forced-command wrapper in `scripts/vm/`).
A summary of the OpenClaw config without secrets is published by cron job to
`/tmp/openclaw/config-summary.json`.
The MCP server (`query/mcp_server.py`) may need to log each tool invocation if it does
not already; that is a logging addition, not behavior change.

## 8. Documentation deliverables

- DOC1. Blameless postmortems in `Doc/Postmortems/` (or similar), format: summary,
  impact, timeline, detection, root cause, fix, prevention. Initial set, from real
  incidents already recorded in `Doc/step-5-requirements.md`:
  1. Valid single-source answer refused by `min_hits=2`.
  2. Tool not visible to OpenClaw (needs both `tools.allow` and
     `tools.sandbox.tools.alsoAllow`).
  3. Privacy refusal originating in OpenClaw's own workspace file (`SOUL.md`/`MEMORY.md`).
  4. 8-14B models failing to emit structured tool calls.
  5. Signal tool missing because the MCP server was down at session start (this
     project's most recent incident).
  6. NFS permission denied after uid mapping / `manage-gids`.
- DOC2. Runbook entries: one short page per warning the console can show, derived from
  `scripts/triage.sh` cases (symptom, check, fix). Console warnings link to them.
- DOC3. A gold question set (see §10) documented with how it is used.
- DOC4. README section: how to run the console, what it shows, what it does not do.

## 9. Technology and installation

- T1. Backend: Python, FastAPI (already in `requirements.txt`), uvicorn. No new Python
  dependency unless a need is shown.
- T2. Frontend: React + TypeScript, built with Vite; charts via a small library
  (decision Q5). Static build served by the console API process, so there is one
  process to run.
- T3. `REQUIREMENTS.md` gets a new subsection (Node.js LTS version, `npm` commands,
  console run command and port) as part of implementation, as that file requires.
- T4. Run command, analogous to the others: `./run_console.py --config
  config/console_config.yaml`. A `console_config.example.yaml` is tracked; any file
  with personal paths is git-ignored, as with `ingest_config.yaml`.
- T5. Service supervision follows the same approach decided for HYR-01 (systemd
  `--user` unit), but is not required for v1.

## 10. Quality and verification

- Q-1. **Gold question set.** About 20-30 real questions with expected source files,
  stored with personal data scrubbed or kept untracked. A script runs them through the
  engine and reports pass/fail; used to detect regressions when thresholds change and
  as a comparison baseline on page 2.
- Q-2. Backend unit tests for the log parsers (using fixture log excerpts, including the
  maintenance old-failure-then-OK case) and for read-only guarantees (a test that a
  write attempt against the opened handles fails).
- Q-3. Verify the console does not change `manifest.db` or `lancedb/` (checksum or mtime
  before and after a session of use).
- Q-4. Verify the Signal path is unaffected while the console runs and when it is killed.
- Q-5. Frontend: type-checked build, and a smoke test that each page renders against the
  synthetic dataset.

## 11. Delivery order (small and demonstrable first)

1. Console API skeleton, read-only handles, health endpoint, synthetic dataset script.
2. Page 1 (Index health). Fixes real gaps first: cause categories for failures, lock
   files (HYR-04).
3. Page 2 (Query explorer).
4. Page 4 (Tool-call monitor), after Q2 and Q4 are resolved.
5. Page 3 (Query log analytics).
6. Postmortems and runbooks in parallel from step 2 onward.

A working slice of pages 1, 2 and 4 is preferred over four half-built pages, per
`improvements.md`.

## Decisions and open questions

Resolved so far:
1. **Tool-call log transfer:** use the `ragr` user on `npabot-u24` (option A, §7).
2. **Structured query log:** yes. Add a JSONL sidecar written by `query/logging_setup.py`
   (logging only, no change to retrieval); the text log stays as is. Requirement FR-3.5
   becomes: the console reads the JSONL where present and falls back to the text parser for
   older days.
3. **Frontend:** React and TypeScript are both required (T2).
4. **Tool-call detection:** the marker message is documented in `Doc/step-5-requirements.md`
   (line about OpenClaw detecting a model that dumps tool-call JSON as text): the log text
   is `Assistant reply looks like a tool call, but no structured tool invocation was
   emitted`. It does **not** appear in any log copy available so far (2026-09-05, 2026-10-29;
   2026-10-30 was unreadable, see HYR-10), and the daily files hold only startup, policy
   and channel events (20-60 lines). Before FR-4.1 is firm: confirm which log level or
   file records per-turn tool events, and reproduce the message with a small model.
   Until then FR-4.1 is based on this documented text. A successful call is currently
   visible on the desktop side (MCP `POST /mcp` in `logs/run_stdout.log`, query log).

5. **File placement:** keep `Doc/step-9-requirements.md`; only dependencies and run command go
   in `REQUIREMENTS.md`.
6. **Scope of v1:** page 3 (query log analytics) is **not** dropped; all four pages are in v1.
   The delivery order in §11 stays as the build sequence, not a cut line.
7. **Ticket linkage:** tickets stay as `Doc/Issues/HYR-nn.md` for now. A limited Jira
   instance may be installed later (undecided). To keep that open: ticket IDs `HYR-nn` are
   stable and never reused, and each ticket gets a small front-matter block (id, severity,
   status) so the console can link to Markdown today and a Jira URL template later.
8. **Per-turn agent events (resolved from the 2026-10-30 log):** OpenClaw logs
   `subsystem=auto-reply/agent-turn-timing` records with a `milestone` field. The record
   `milestone=tool_execution_started` carries `runId`, `sessionKey` (`agent:main:main`),
   `totalMs` (time from message receipt to the tool starting) and `spans`. The web UI
   transcript (`http://127.0.0.1:18789/chat/main`) shows the same call as the line item
   "Hybrid-rag Ask Documents <question>". The home-router question of 2026-10-30 09:57 PDT
   matches: `totalMs=50248` before the tool started (the desktop then answered in 14 s).
   FR-4.1/4.2 use these records as the "structured tool call happened" signal, and
   FR-4.6 below adds time-to-tool.

Still open:
9. The log line for the failure case ("Assistant reply looks like a tool call, but no structured
   tool invocation was emitted") has still not been seen in a readable log. Reproduce it with
   a small model (e.g. the 8-14B models that failed) to confirm the field names before FR-4.1
   is final. Absence of a `tool_execution_started` milestone for a turn is the fallback signal.
10. Other gateway events worth surfacing on page 4 or the status header, seen on 2026-10-30:
    `host timing gap detected: process was frozen ~32123198ms` (VM suspended about 9 h),
    cron/provider preflight timeouts against Ollama on the desktop (2500 ms deadline), and
    `memory sync failed ... embedding provider "local" is configured but unavailable`.
    Decide which are in scope.
