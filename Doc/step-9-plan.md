# Step 9 Plan: Implementation, Milestones, Test Plan, Documentation

Draft for review. Implements `Doc/step-9-requirements.md` (the requirement IDs FR-x.y, C#, P#,
T# below refer to it). Nothing in this plan is built yet. Sizes are relative effort
(S = under a day, M = 1-3 days, L = 3+ days), not dates.

---

## 1. Design decisions that shape the plan

| # | Decision | Reason |
|---|---|---|
| D1 | New Python package `console/` (API + readers) and `console/web/` (React + TypeScript, Vite). Entry point `run_console.py`, config `config/console_config.yaml` (tracked example, personal copy git-ignored). | Matches repo layout (`run_*.py`, `config/`); separate process (C1). |
| D2 | Default port **8300**, bound to `127.0.0.1` (C4). Free today: 8080 Open WebUI, 8100 HTTP server, 8200 MCP, 11434 Ollama, 18789 OpenClaw. | Avoid clashes. |
| D3 | Readers are small modules, one per source: `manifest_reader`, `lance_reader`, `maintenance_log`, `query_log` (text and JSONL), `agent_log` (OpenClaw), `config_summary`. All take a path and open read-only. | Testable with fixture files; read-only enforced in one place (C2). |
| D4 | **Structured query log first.** JSONL sidecar `logs/query_YYYY-MM-DD.jsonl` from `query/logging_setup.py` + engine call sites, in M1. | Data accumulates from day one; page 3 needs weeks of history, and text parsing stays only as fallback. Logging only, no retrieval change (NG2). |
| D5 | Explorer reuses the engine. Needs a retrieval-only entry point; M3 extracts the existing retrieval steps of `query/engine.py` into `retrieve(query, config)` that `answer_query` then calls. Behavior must be bit-identical, proven by a golden test (T-ENG-1). | Single code path (FR-2.6); only production-code refactor in the whole step. |
| D6 | Agent logs: a pull script on the desktop (`scripts/pull_agent_logs.sh`, cron daily + on demand) copies `/tmp/openclaw/openclaw-*.log` and `config-summary.json` from `ragr@npabot-u24` into `logs/agent/` (git-ignored). The console reads the local copies only, so the console never needs SSH. | Retention beyond VM `/tmp`; keeps the console read-only and offline-capable; privacy (P1). |
| D7 | **pytest for everything** (owner decision: no other framework without a strong reason). Backend, parsers, contract, shell-harness and UI smoke tests (via `pytest-playwright`, added in the first UI milestone) all run under pytest. A JS test runner (Vitest) is added only if frontend logic grows beyond what UI smoke tests can check; that needs a written reason. `requirements-dev.txt`, `pytest.ini`, new `tests/` tree. | One test command; no new services. |
| D10 | Development happens on branch **`console`** (owner decision), kept mergeable into `main`: changes to existing files stay small and isolated (`query/engine.py` in M3, `query/logging_setup.py` and call sites in M1, `scripts/triage.sh`), new code lives in `console/`, `tests/`, `scripts/`. Merge `main` into `console` regularly. | Easy eventual merge. |
| D8 | Frontend build output (`console/web/dist`) is served by the API process (T2). `node_modules` and `dist` git-ignored. Node v20 and npm 10 are installed. | One process to run and supervise. |
| D9 | Console health is part of `scripts/triage.sh` from M1 onward (see §4), extended per milestone. | Operational features must be diagnosable by the same tool. |

## 2. Prerequisites (done before or inside M0)

| Item | Why | Status |
|---|---|---|
| HYR-10 cron (`setfacl` every 5 min) | Agent log readable as `ragr` | Installed by owner; verify by test T-PULL-1 |
| HYR-04 exclude `~$*` lock files | Page 1 failure table should not be dominated by lock files | Open; do in M2 |
| HYR-08 `.gitignore` entries | Console caches, `logs/agent/`, `console/web/node_modules`, `dist` | Open; do in M0 |
| HYR-09 `ragr` hardening (forced command) | Pull job runs as `ragr`. Works with plain bash today; with `BOT_WRAPPER=1` the pull script uses verbs `logs`, `log DATE`, `config` | Open; independent of this step |
| Open question 9 (failure-case message) | Final FR-4.1 field names | Reproduce in M4 |

## 3. Milestones

Each milestone ends with: tests green, `scripts/triage.sh` console checks updated, docs
updated, one commit series on `main` (or a feature branch if preferred), and a short demo
against the synthetic dataset.

### M0: Scaffolding and synthetic data (S-M)
- **Deliver:** `console/` package skeleton, `run_console.py`, `config/console_config.example.yaml`,
  `tests/` + `pytest` config, `requirements-dev.txt`, `.gitignore` entries (HYR-08 part),
  `scripts/make_synthetic_data.py` generating a self-contained demo tree
  (`demo_data/`: small `manifest.db` with all statuses, LanceDB table, text + JSONL query
  logs, maintenance log, sample OpenClaw logs, config summary) with fake paths and queries.
- **Covers:** P2, P4, D7.
- **Exit:** `pytest` runs (one smoke test); synthetic generator is deterministic
  (same seed, same checksums); no real data appears in `demo_data/` (test T-PRIV-1).
- **Triage:** none yet.
- **Docs:** README "Operator console" stub; step-9 "As built" section started.

### M1: Backend foundation and structured query log (M-L)
- **Deliver:**
  - Read-only readers for manifest, LanceDB, maintenance log, text query log (C2, D3).
  - FastAPI app: `/api/v1/health`, `/api/v1/index/summary` (counts only), static file serving,
    bind/port/demo-mode config, JSON error bodies (API4).
  - JSONL query log (D4): one record per query: `ts, query, n_sources, sources[], total_s,
    embed_s, retrieve_s, gen_s, gen_tokens, tok_per_s, outcome (answered | no_relevant |
    refused | error | timeout), branch details per source, thresholds in effect, caller
    (cli | http | mcp)`. Written by the engine call sites; the text log is unchanged.
  - Status header data (FR-X.1): MCP :8200 listening, Ollama, last maintenance result,
    freshness.
- **Covers:** C1-C5, API1-API4, FR-1.3 (reader), FR-X.1, FR-3.5.
- **Exit:** read-only proof tests pass (T-RO-*); console can be killed and started while the
  MCP server keeps serving (T-ISO-1); JSONL written for CLI, HTTP and MCP callers; text
  log byte-identical to before for the same queries (T-LOG-2).
- **Triage:** new checks C1-C4 in §4.
- **Docs:** README run instructions, config reference, `REQUIREMENTS.md` section (Node, dev
  deps), API overview (generated OpenAPI link), HYR ticket for any defect found.

### M2: Page 1, Index health (M)
- **Deliver:** `/api/v1/index/summary` (full), `/index/failures`, `/maintenance/runs`;
  failure cause classifier (permission denied, lock file, damaged file, image-only/no text,
  low-confidence OCR, other); ticket link map (`HYR-03/04/06`); staleness rule (default 36 h,
  FR-1.6); ANN-threshold gauge (FR-1.7); React page with tables, filters, sorting; HYR-04
  fix (exclude `~$*` and `.~lock.*#` in ingest) so the numbers are meaningful.
- **Covers:** FR-1.1 to FR-1.7.
- **Exit:** numbers match an independent SQL count on the real manifest (T-P1-1: 2,534 files /
  509 failed as of the last report, re-measured at test time); last-run result uses only the
  last `run end` line (T-P1-2, the earlier false-FAILED case); page renders on synthetic data.
- **Triage:** add check C5 (index API consistent with manifest) in §4.
- **Docs:** user guide page "Index health", runbook entries for each warning (stale index,
  failed run, failure categories), HYR-04 closed.

### M3: Page 2, Query explorer (L)
- **Deliver:** `retrieve()` extraction in `query/engine.py` (D5); `POST /api/v1/explore`
  (dense hits, BM25 hits, fused ranking, per-leg ranks/scores, gate results, excerpts,
  timings, optional generation); explorer log kept separate from production logs (FR-2.5);
  React page with side-by-side legs and gate explanations.
- **Covers:** FR-2.1 to FR-2.6.
- **Exit:** golden test shows `answer_query` results unchanged before/after the refactor on
  at least 20 stored queries (T-ENG-1); explorer shows the same fused ranking as the
  production query log's `fusion detail` line for the same query (T-P2-1); the `min_hits`
  case is reproduced and explained on screen (T-P2-3); no write to production `query_*.log`
  or JSONL (T-P2-4).
- **Triage:** engine end-to-end check reuses `retrieve()` (cheaper than a full answer).
- **Docs:** user guide "Query explorer" including how to read distances/BM25 signs;
  step-5 note that `retrieve()` exists.

### M4: Agent log pull and Page 4, Tool-call monitor (L)
- **Deliver:** `scripts/pull_agent_logs.sh` (SSH as `ragr`, read-only, idempotent, keeps
  history in `logs/agent/`, supports `BOT_WRAPPER=1`); agent log parser (milestones, tool
  policy removals, MCP connect failures, frozen-host events); MCP-side invocation counts
  from the JSONL log with `caller=mcp`; `/api/v1/toolcalls/summary`; React page grouped by
  model and day; time-to-tool chart; "session started while MCP down" flag. Reproduce the
  failure-case message with a small model on the VM to fix FR-4.1 field names (open
  question 9).
- **Covers:** FR-4.1 to FR-4.6, D6.
- **Exit:** agent-side and desktop-side counts reconcile on a controlled test (send 5
  Signal/webchat questions, expect 5 `tool_execution_started` and 5 `caller=mcp` records,
  T-P4-2); parser handles all three real sample logs (09-05, 10-29, 10-30) (T-P4-1);
  failure-case sample either captured or the fallback rule documented (T-P4-3).
- **Triage:** checks C6-C8 in §4 (pull job freshness, ACL mask, config summary freshness).
- **Docs:** user guide "Tool-call monitor", runbook for "tool never called", note on
  retention (`/tmp` volatility), HYR-10 closed when pull verified across a day boundary.

### M5: Page 3, Query log analytics (M)
- **Deliver:** `/api/v1/queries/stats` and `/queries/slow`; aggregation from JSONL with text
  fallback for older days; latency percentiles, outcome rates, slow/no-result tables, top
  terms; masking switch (FR-3.6, P3); React page with charts.
- **Covers:** FR-3.1 to FR-3.6.
- **Exit:** aggregates equal independently computed values on a fixture month (T-P3-1); text
  and JSONL parsers agree on days that have both (T-P3-2); masking removes query text and
  paths from API and UI (T-PRIV-2).
- **Triage:** none new.
- **Docs:** user guide "Query analytics", definition of each metric and outcome.

### M6: Gold set, postmortems, runbooks (M)
- **Deliver:** gold question set format + runner (`scripts/run_gold_set.py`, stored privately
  or scrubbed, see requirements Q7), pass/fail report; page 2 compare view against the gold
  set (Q-1); six postmortems (DOC1); one runbook page per console warning (DOC2), linked from
  UI warnings (FR-X.2).
- **Exit:** gold runner reports a baseline; deliberately changing `relevance_min_hits`
  in a scratch config makes it fail (T-GOLD-2); every warning in the UI resolves to an
  existing runbook file (T-DOC-1 link check).
- **Triage:** menu items link to the same runbooks.
- **Docs:** the runbooks and postmortems themselves.

### M7: Hardening, packaging, acceptance (M)
- **Deliver:** systemd `--user` unit for the console (alongside HYR-01's MCP unit, shared
  install doc); demo mode polished and screenshots from synthetic data only; frontend lint
  and type-check in a single `make check` (or script); performance pass (API3); security
  review against requirements §2 and §6; final README and "As built" section.
- **Exit:** full test suite green; acceptance walkthrough (§5.8) signed off; Signal path
  unaffected for 24 h with console running (T-ISO-2).
- **Triage:** full console section, unit status checks (§4).

### Dependency overview

```
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7
          \_ JSONL logging starts accumulating data here (feeds M5)
M4 needs: HYR-10 cron + pull job; M6 needs real incidents' notes (from step-5 doc)
```

M3 and M4 are independent after M1 and may be swapped. The order above follows the
"pages 1, 2, 4 first" rule in `improvements.md`; page 3 is still delivered (M5).

## 4. Extending `scripts/triage.sh`

Add one menu entry and fold the cheap checks into "Run all quick checks".

**New menu item 10: "Operator console not working / shows stale or no data".**

| ID | Check | Method (read-only) | On failure | Added in |
|---|---|---|---|---|
| C1 | Console process up | port 8300 listening (or configured port); `pgrep -f run_console.py` | offer to start it (`confirm`), or `systemctl --user start` once the unit exists | M1 |
| C2 | API healthy | `GET /api/v1/health` returns 200 with expected JSON; report version | show body/error text; point to console log | M1 |
| C3 | Read-only handles | `/api/v1/health` reports `read_only: true` for manifest and LanceDB; fail if false | hard fail, no auto-fix | M1 |
| C4 | Data sources found | health lists each source path and whether present (manifest, lancedb, logs dir, JSONL for today) | name the missing path | M1 |
| C5 | Index summary matches manifest | compare `files` count from API with `sqlite3` count on `manifest.db` | report the difference | M2 |
| C6 | Agent log pull freshness | newest file in `logs/agent/` and its mtime; warn if older than 36 h | offer to run `scripts/pull_agent_logs.sh` | M4 |
| C7 | VM log readable (HYR-10) | `bot_logtext` already detects permission denied; add the ACL-mask hint and a pointer to the cron line | print the cron line from HYR-10 | M4 (log hint exists) |
| C8 | Config summary fresh | `config-summary.json` mtime on VM (via `ragr`) younger than 15 min | point to the `nick` cron job | M4 |
| C9 | JSONL query log written | today's `query_*.jsonl` exists and grows after a test query (only checked when `--yes` is not set, to avoid generating traffic) | explain that `logging_setup` is not writing | M1 |
| C10 | Systemd unit state | `systemctl --user is-active hybrid-rag-console` (and MCP unit) | offer start/enable | M7 |

Rules to keep consistent with the existing script: read-only by default; each fix is behind
`confirm "...(y/N)"` and honors `-y`; colors only on a TTY; `--yes` never starts traffic
generating actions unless a problem was detected; every failure ends with a link to its
runbook path. The status header (FR-X.1) and C1-C4 share the same endpoint, so the console
and `triage.sh` can never disagree about what "up" means.

Tests for the triage changes: T-TRI-1 to T-TRI-5 in §5.5.

## 5. Test plan

### 5.1 Strategy and levels

| Level | Tooling | What it proves | Runs |
|---|---|---|---|
| Unit | pytest | parsers, classifiers, aggregations, masking | every change |
| Contract | pytest + FastAPI TestClient, OpenAPI schema check | endpoint shapes, errors, pagination | every change |
| Read-only / isolation | pytest + filesystem checks | console cannot modify data or affect Signal path | every change + M7 soak |
| Integration | pytest on synthetic dataset; selected tests on the real corpus (marked `real`, skipped by default) | readers vs. real files, counts vs. SQL | before each milestone close |
| Frontend unit | Vitest + RTL | components, formatting, empty/error states | every change |
| UI smoke | Playwright against `run_console.py --demo` | each page renders, key interactions work, no console errors | per milestone + CI-style script |
| Shell | bats-style script tests or a small bash harness with fake `ssh`/`curl` | `triage.sh` console checks and fixes | per milestone |
| Manual acceptance | checklist §5.8 | end-to-end usefulness | M7 |

Test data policy (P1, P2): automated tests use only the synthetic dataset and small hand-made
fixtures. Tests marked `real` read the real corpus locally and never print or store query
text; they are excluded from any shared run.

### 5.2 Requirement-to-test traceability

| Requirement | Test IDs | Milestone |
|---|---|---|
| C1 separate process | T-ISO-1, T-ISO-2 | M1, M7 |
| C2 read-only | T-RO-1, T-RO-2, T-RO-3 | M1 |
| C3 no new datastore | T-RO-4 | M1 |
| C4 bind address | T-SEC-1 | M1 |
| C5 existing endpoints untouched | T-ISO-3 | M1 |
| API1 to API4 | T-API-1 to T-API-5 | M1 onward |
| FR-1.1, 1.2 | T-P1-1 | M2 |
| FR-1.3 | T-P1-2 | M1, M2 |
| FR-1.4, 1.5 | T-P1-3, T-P1-4 | M2 |
| FR-1.6 | T-P1-5 | M2 |
| FR-1.7 | T-P1-6 | M2 |
| FR-2.1, 2.2 | T-P2-1, T-P2-2 | M3 |
| FR-2.3 | T-P2-3 | M3 |
| FR-2.4 | T-P2-5 | M3 |
| FR-2.5 | T-P2-4 | M3 |
| FR-2.6 | T-ENG-1 | M3 |
| FR-3.1 to 3.4 | T-P3-1, T-P3-3 | M5 |
| FR-3.5 | T-LOG-1, T-LOG-2, T-P3-2 | M1, M5 |
| FR-3.6, P3 | T-PRIV-2 | M5 |
| FR-4.1 to 4.4 | T-P4-1 to T-P4-4 | M4 |
| FR-4.6 | T-P4-5 | M4 |
| FR-X.1 | T-API-6, T-TRI-1 | M1 |
| FR-X.2 | T-DOC-1 | M6 |
| FR-X.3 | T-UI-1 | each |
| P1, P2, P4 | T-PRIV-1, T-PRIV-3 | M0, M7 |
| Q-1 gold set | T-GOLD-1, T-GOLD-2 | M6 |

### 5.3 Test cases (selected, with pass criteria)

**Isolation and read-only**
- T-RO-1: open `manifest.db` through the reader and attempt `INSERT`/`UPDATE`/`PRAGMA`
  writes: each raises; file checksum unchanged after a full API session.
- T-RO-2: LanceDB handle: `add`, `delete`, `create_index` all fail or are not exposed; table
  version unchanged after the session.
- T-RO-3: console started with log directory mode 555: still serves; never creates files in
  `logs/` (explorer log goes to its own directory, FR-2.5).
- T-RO-4: no new files appear outside the configured cache/log directories (compare a
  directory snapshot before and after).
- T-ISO-1: with the MCP server serving requests in a loop, start, stop and `kill -9` the
  console; MCP request success rate stays 100 %.
- T-ISO-2 (soak): console running for 24 h during normal Signal use; no change in MCP p95
  latency beyond noise; no errors in `query_*.log` attributable to the console.
- T-ISO-3: `query/server.py` and `query/mcp_server.py` unchanged apart from the logging calls
  (diff review + the existing end-to-end checks in `triage.sh` pass).

**Logging**
- T-LOG-1: JSONL record has all required fields for caller `cli`, `http`, `mcp`, and for each
  outcome (answered, no_relevant, refused, error, timeout).
- T-LOG-2: the human-readable text log is byte-identical to the pre-change output for the
  same stored queries (excluding timestamps).

**Page 1**
- T-P1-1: counts by type and status equal independent SQL; totals equal 100 %.
- T-P1-2: maintenance fixture with old FAILED lines followed by a final OK reports OK; the
  reverse reports FAILED.
- T-P1-3/4: classifier puts each fixture failure in the expected cause; unknown goes to
  "other"; every category maps to a ticket link where one exists.
- T-P1-5: staleness warning at threshold boundaries (35 h 59 m no, 36 h 01 m yes) and on a
  FAILED last run.
- T-P1-6: gauge changes color at the 200k-chunk threshold.

**Page 2**
- T-P2-1: for 20 stored queries, explorer fused ranking equals the ranking in the production
  `fusion detail` log line.
- T-P2-2: legs shown correctly for chunks found by dense only, sparse only, both.
- T-P2-3: the `min_hits=2` single-source case displays "failed gate: min_hits" with values.
- T-P2-4: after 10 explorer runs the production text and JSONL logs have zero new lines.
- T-P2-5: generation toggle off by default; on returns an answer and timing.
- T-ENG-1: golden test, `answer_query` output (sources, order, scores, answer text where the
  LLM is stubbed) identical before and after the `retrieve()` extraction.

**Page 3**
- T-P3-1: aggregates (counts, p50/p95, rates) equal values computed independently from a
  fixture month; empty days handled.
- T-P3-2: for days with both formats the two parsers give the same aggregates.
- T-P3-3: slow-query threshold and recurring-term counts configurable and correct.
- T-PRIV-2: with masking on, no query text or file path appears in any API response or the
  rendered DOM.

**Page 4**
- T-P4-1: parser extracts milestones, tool-policy removals, connect failures, frozen-host
  events from the three real sample logs; unknown subsystems are ignored, not errors.
- T-P4-2: controlled run: N questions produce N agent-side starts and N `caller=mcp`
  records; a deliberately stopped MCP server produces a "session started while MCP down"
  flag and zero MCP records.
- T-P4-3: failure-case sample (small model) is detected, or the documented fallback
  (turn without milestone) flags it.
- T-P4-4: grouping by model and day correct when the model changes mid-day.
- T-P4-5: time-to-tool percentiles correct on a fixture (includes the 50,248 ms real record).
- T-PULL-1: pull script: first run copies all logs; second run copies nothing new
  (idempotent); a day-boundary run keeps both days; unreadable log produces a clear error
  (HYR-10 condition), not an empty file.

**API, security, privacy, docs**
- T-API-1..5: schema validation of every endpoint, pagination limits, JSON error body for
  bad input and missing source, response time under 1 s for pages 1 and 3 at current size.
- T-API-6: health reports all sources and `read_only` flags.
- T-SEC-1: default bind is 127.0.0.1; LAN bind requires explicit config and logs a warning.
- T-PRIV-1: grep of `demo_data/` and tracked files for personal markers (real hostnames of
  documents, account-number patterns, the Signal number) finds nothing.
- T-PRIV-3: screenshots directory contains only images generated from demo mode (checked by
  generation script, manual review).
- T-DOC-1: every runbook link in the UI and every doc link in the README resolves to a file.
- T-UI-1: Playwright: each page loads in demo mode with no console errors and shows
  non-empty content; empty-state and error-state views render.

**Gold set**
- T-GOLD-1: runner executes all questions against the real index and reports pass/fail per
  question and overall.
- T-GOLD-2: sensitivity: lowering relevance settings in a scratch config flips at least one
  result and the runner reports it.

### 5.4 Test data

- `scripts/make_synthetic_data.py` (M0): deterministic, seeded; includes every manifest
  status, two failure categories per type, multi-day query logs in both formats, maintenance
  history with an old failure then success, OpenClaw sample logs, and a config summary.
- Real sample logs for parser tests are scrubbed copies in `tests/fixtures/` (Signal number
  and session ids replaced). The unscrubbed copies stay untracked.

### 5.5 Triage tests

Harness with fake `ssh`, `curl`, `ss` on a temporary `PATH`, driving `scripts/triage.sh -y N`:
- T-TRI-1: console down -> check C1 FAIL and a start offer; with `-y` it starts the console.
- T-TRI-2: API 500 -> C2 FAIL with body text; healthy -> OK with version.
- T-TRI-3: health reports `read_only: false` -> C3 FAIL, no auto-fix offered.
- T-TRI-4: stale `logs/agent/` -> C6 WARN with offer to run the pull script; `-y` runs it.
- T-TRI-5: VM log unreadable -> C7 prints the HYR-10 hint and does not report "no failures"
  (regression test for the earlier false-OK).
- Existing menu items 1-9 keep working (smoke run of `triage.sh -y 9` in the harness).

### 5.6 Entry and exit criteria per milestone

Entry: previous milestone exit met, requirements for this milestone not changed since last
review. Exit: all tests listed for the milestone pass; no open defect above "Low"; docs and
triage items for the milestone merged; demo given on the synthetic dataset; any defect found
logged as `HYR-nn`.

### 5.7 Defects and regressions
Each defect gets a ticket in `Doc/Issues/` and a test that would have caught it. Any change
that touches `query/` also runs the existing end-to-end checks (`triage.sh 7`) and T-ENG-1.

### 5.8 Final acceptance walkthrough (M7)
1. Start the console in demo mode and walk through all four pages with the narrative of a
   real incident (e.g. the Signal "tool not found" caused by the MCP server being down).
2. Start it on real data (localhost only): page 1 matches the manifest; page 4 shows the
   router-IP question of 2026-10-30 with its time-to-tool; page 2 explains why a chosen query
   returned its sources; page 3 shows at least two weeks of JSONL history.
3. Stop the MCP server: the status header, page 4 flag and `triage.sh 1` agree.
4. Confirm read-only (checksums of `manifest.db` and the LanceDB directory before/after).
5. Review wording of README against the honesty constraint (only what is built).

## 6. Documentation plan

| Document | Content | When |
|---|---|---|
| `Doc/step-9-requirements.md` | Keep as the requirement source; add "As built" section per milestone with deviations | every milestone |
| `Doc/step-9-plan.md` (this file) | Update status column and decisions as work proceeds | every milestone |
| `README.md` | New "Operator console" section: what it is, screenshots (demo data only), how to run, how to run demo mode, link to guide | M0 stub, M7 final |
| `REQUIREMENTS.md` | New section: Node.js 20+, npm, `requirements-dev.txt`, console run command, port | M1 |
| `config/console_config.example.yaml` | Every key commented; personal copy git-ignored | M1 |
| `Doc/console-guide.md` | User guide: one section per page, how to read each chart/table, glossary of outcomes and statuses, masking | per page milestone |
| `Doc/Runbooks/*.md` | One short page per warning (symptom, check, fix, link to triage menu item): stale index, failed run, MCP down, tool never called, slow time-to-tool, log unreadable (HYR-10), pull job stale, console down | M2, M4, M6 |
| `Doc/Postmortems/*.md` | Six blameless postmortems (requirements DOC1), format: summary, impact, timeline, detection, root cause, fix, prevention | M6 |
| API reference | Generated from FastAPI OpenAPI; committed snapshot `Doc/api/openapi.json` plus short usage notes | M1, refreshed per milestone |
| `Doc/Issues/` | Tickets for defects and deferred ideas; front matter (id, severity, status) added to existing tickets in M0 (decision 7) | M0 onward |
| `scripts/triage.sh` header comment and README troubleshooting section | New menu item 10 and checks C1-C10 | per milestone |
| `Doc/Hybrid_RAG_overview.pptx` | Optional new slide: "Operator console" (built vs. planned). Only after M2 and with demo screenshots | after M2/M7 |
| Interview/resume notes (not committed, personal) | A short list of what was built, using the honesty constraint | after M7 |

Documentation rules: state only what exists; mark planned items as planned; no real data in
screenshots or examples; each runbook is linked from the UI warning that references it; each
milestone's docs are part of its exit criteria.

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Free-text log parsing breaks on a format change | Pages 1 and 3 wrong | JSONL first (D4); parser tests on real samples; unknown lines ignored and counted |
| `retrieve()` refactor changes behavior | Breaks the working Signal path | Golden test T-ENG-1 before merging; keep diff minimal; revert path documented |
| Per-turn agent events not logged at the current log level | Page 4 thin | Confirmed one `tool_execution_started` record exists; if more fields are needed, raise OpenClaw log level on the VM (change by owner, not by this project) |
| VM `/tmp` logs lost on reboot or ACL mask reset | Gaps in history | Daily pull (D6), HYR-10 cron, C6/C7 checks |
| Scope growth (four pages + docs) | Unfinished work | Milestone exits are shippable slices; M6 and M7 are the only items that can slip without losing a page |
| Personal data leaks into screenshots or fixtures | Privacy | Demo mode only, scrubbed fixtures, T-PRIV tests, masking option |
| Frontend tooling friction (Vite, Playwright browsers) | Delays | M0 proves the toolchain on a hello-world page before any feature work |
| Contention with Ollama GPU when explorer generates | Slower Signal replies | Generation off by default (FR-2.4); explorer rate-limited |

## 8. Decisions (owner, 2026-10-30) and status

| Question | Decision |
|---|---|
| Branching | Work on branch `console`; keep it mergeable into `main` (D10) |
| Test stack | pytest unless there is a strong reason otherwise (D7) |
| Port and package name | 8300 and `console/` accepted |
| systemd unit for the MCP server (HYR-01) | Deferred to M7, installed together with the console unit |
| M3/M4 order | Unchanged (interchangeable after M1) |

| Milestone | Status |
|---|---|
| M0 Scaffolding and synthetic data | Done on `console` (see "As built" in the requirements doc when written): package, config, pytest, `.gitignore`, generator, 12 tests |
| M1 Backend foundation and structured query log | Done on `console` (see "M1 as built" below) |
| M2 Page 1, Index health | Done on `console` (see "M2 as built" below) |
| M3 Page 2, Query explorer | Done on `console` (see "M3 as built" below) |
| M4 Agent log pull and Page 4, Tool-call monitor | Done on `console` (see "M4 as built" below); real failure-case sample still missing |
| M5 Page 3, Query log analytics | Done on `console` (see "M5 as built" below) |
| M6 to M7 | Not started |

### Findings during M0 that affect later milestones
- The real manifest has 285 `ocr_low_confidence` files and 509 `failed` (413 "OCR produced no text", 12 permission
  denied, the rest low-confidence OCR, lock files and damaged files). The earlier "75 low-OCR files" figure was a
  different cut (below the 40.0 failure threshold in the report); M2 must define the categories precisely and
  test them against SQL (T-P1-1).
- The real query logs contain Open WebUI's automatic follow-up/title prompts (queries starting `### Task:`).
  Page 3 must classify these as `system` queries so they do not distort rates and top terms (add to FR-3.4/T-P3-3).
- The synthetic agent log contains one line imitating the "looks like a tool call" message. Its real field names
  are still unconfirmed (open question 9 in the requirements); the fixture must be replaced by a real sample in M4.

### M1 as built (2026-10-31)
- `console/`: `config.py`, `health.py`, `api.py`; readers `sqlite_ro` (mode=ro + `query_only`, write probe),
  `lance_reader` (count/schema only), `maintenance_log` (run decided by its own end line), `query_log` (text and
  JSONL parsers into one `QueryEvent`; flags Open WebUI `### Task:` prompts as system queries).
- `run_console.py` (`--demo`, `--host`, `--port`; warns on non-loopback bind). Endpoints: `/api/v1/health`,
  `/api/v1/index/summary`, `/docs`, `/openapi.json` (snapshot in `Doc/api/openapi.json`), `/` placeholder or built UI.
- `query/structured_log.py` + 5 small edits in `query/engine.py` (`caller` argument, timing marks, one
  `log_query_event` call per outcome) and `caller=` at the three call sites. Text log verified unchanged against
  golden lines captured before the change. A logging failure never affects an answer (tested).
- `scripts/triage.sh` menu item 10 and a non-fatal console line in "run all": checks C1-C4 and C9, fake-`ss`/`curl`
  tests, `CONSOLE_START_CMD` override for tests. Header comment fixed (`BOT_USER` default `ragr`).
- Tests: 66 pass (`python -m pytest`, about 14 s). Verified manually on real data: health, index summary
  (2,539 files, 17,983 chunks) and unchanged `manifest.db` and `lancedb/` checksums after a console session.
- Decisions made while building:
  - **SQLite WAL side files.** The manifest uses WAL mode, and a read-only connection still creates/touches
    `manifest.db-wal` and `-shm`. They carry no data; the main file is never modified. Requirement C2 and tests
    T-RO-3/4 therefore exclude these two names. Opening with `immutable=1` was rejected because it would return
    stale or inconsistent data while the maintenance run writes.
  - **Outcome vocabulary** in the JSONL log: `answered | no_relevant | general_knowledge | error`. "Refused" and
    "timeout" (FR-3.2) cannot be told apart from an answer inside the engine (a refusal is generated text; the 60 s
    MCP timeout happens in OpenClaw), so page 3 derives "slow" from `total_s` and takes timeouts from the agent
    logs (page 4).
  - `gen_tokens` / `tok_per_s` are null on `main` (token metrics exist only on branch `alternate`); the text-log
    parser fills them when the old log has a `generation:` line.
- Operational note: the running `run_mcp_server.py` and `run_server.py` processes load the old engine until
  restarted, so no JSONL records appear until then (`triage.sh 10` warns about this).
- Merge note: `alternate` also edits `query/engine.py` and `query/logging_setup.py`. This milestone does not touch
  `logging_setup.py`; expect a small textual conflict in `engine.py` (timing/metrics lines) if both are merged.

### M2 as built (2026-10-31)
- **Backend:** `console/failures.py` (cause classifier, ticket and runbook map, path/message masking), extended
  `sqlite_ro.summary()` and `failures()`; endpoints `/api/v1/index/summary` (outcome groups, percentages of attempted
  files, types, causes, ANN gauge), `/index/failures` (cause/type/status/path filters, sort, pagination, validated),
  `/index/causes`, `/maintenance/runs`. First request is warmed up (lancedb import moved to startup): real-data
  summary 38 ms, failures 20 ms.
- **Frontend:** React 19 + TypeScript 7 + Vite 8 in `console/web` (npm; `package-lock.json` tracked, `dist` and
  `node_modules` ignored). Hash-routed shell with four tabs; page 1 complete; the others say which milestone builds them.
  Plain CSS with light/dark themes; numbers always printed beside colour; works at 390 px width.
- **HYR-04 fixed in code:** `exclude_prefixes` (default `["~$"]`) in `ingest/classify.py` and config; ticket updated.
- **Triage:** console check C5 (API file count equals a direct manifest count).
- **Docs:** `Doc/console-guide.md`, `Doc/Runbooks/{stale-index,ann-index-needed,index-failure-causes}.md`,
  README, REQUIREMENTS.md (Node, Playwright), HYR-04.
- **Tests:** 116 pass in about 20 s: classifier table, SQL cross-checks, filters/sort/paging/validation, masking, ANN
  states, maintenance runs, ingest classification, docs-link checks, triage C5, and 11 Chromium tests (render with no
  console errors, numbers equal the API, drill-down from cause to file list, sorting/paging, stale banner, API error
  and API-down states, phone width, dark mode).
- **Real-data check (read-only, checksum verified):** 2,539 files: 1,356 indexed (72.1 % of 1,880 attempted), 509
  failed (27.1 %), 15 need attention, 659 skipped. Failure causes: 413 no-text images, 285 low-confidence OCR
  (indexed), 75 OCR below threshold, 15 permission denied, 10 encrypted, 4 near-empty conversions, 3 lock files,
  2 damaged, 1 empty, 1 conversion-script error.
- **Clarified number:** the earlier "75 low-OCR files" are the 75 files *failed* for OCR confidence under 40.0; the
  285 `ocr_low_confidence` files are indexed but flagged. Page 1 shows both, and percentages use attempted files
  (denominator 1,880), not all files seen (2,539).
- **Not done (by design):** nothing is written to the manifest, so the 3 existing lock-file rows stay `failed` until
  the next ingest run reclassifies them as `skipped`.
- **Changes to existing production code:** `ingest/classify.py`, `ingest/config.py` (HYR-04 only).

### M3 as built (2026-10-31)
- **Engine refactor (decision D5):** `query/engine.py` gained `Retrieval` and `retrieve(query, config, *, full=False,
  embed=None)`: embed, dense search, relevance gate, then keyword search and RRF fusion. `answer_query()` now calls it and
  keeps its previous behavior exactly: with `full=False` retrieval stops after a failed gate, so no keyword search runs
  for irrelevant queries as before. **Proof (T-ENG-1):** `tests/golden/engine_results.json` was captured from the engine
  *before* the change (8 scenarios: results plus every dependency call and both prompts); `tests/test_engine_golden.py`
  passes after it, and the text-log golden tests from M1 still pass.
- **Explorer backend:** `console/explorer.py`, `POST /api/v1/explore`. Reuses `retrieve(full=True)`; builds the engine's
  `QueryConfig` from `config/query_config.yaml` (key `query_config`); gate explanation with what-if for 1 to 5 required hits;
  optional generation that mirrors production's branches but never calls `answer_query`; one exploration at a time (429
  when busy); 502 on embedding failure, 503 when the index is missing, 422 on bad input; excerpts capped at 320 chars; no
  vectors in responses; masking of paths and excerpts. Explorer runs are logged only to `logs/explorer/explore_*.jsonl`
  (FR-2.5). The engine is imported lazily, so the console process stays light until the explorer is used.
- **Demo:** `console/demo_embed.py` (hashed bag-of-words embedder) now produces both the demo chunk vectors and the demo
  query vectors, so the demo runs the real LanceDB search, gate and fusion without Ollama (demo threshold 1.35).
- **Frontend:** `pages/QueryExplorer.tsx`, `components/GateCard.tsx`, `components/HitLists.tsx`.
- **Tests:** 144 pass. New: 8 golden engine cases, 14 explorer backend tests (fused ranking equals production's
  `fusion detail` for 20 stored questions; leg labels incl. a crafted keyword-only row; the `min_hits` refusal explained and
  confirmed against production; production logs byte-identical after explorer runs; generation toggle; errors; masking; data
  directory unchanged), 7 browser tests.
- **Real-data check:** fused ranking for a live question (Ollama embeddings) is identical to the production JSONL record
  of the same question (8 rows, branch and rrf score equal); explorer total 77 ms (embed 42 ms, dense 29 ms, keyword 3 ms);
  `manifest.db` checksum unchanged.
- **Deferred:** the plan listed "triage engine check reuses `retrieve()`". Not done on purpose: menu 6 should keep testing
  the full path including generation, which the explorer does not.
- **Merge note:** `query/engine.py` now differs from `alternate` in more places (function split). Resolve by keeping
  `retrieve()` and re-applying alternate's metrics lines in `answer_query()`.

### M4 as built (2026-10-31)
- **`scripts/pull_agent_logs.sh`** (read-only, as `ragr`; `-n` dry run, `-q` for cron, `BOT_WRAPPER=1` supported): copies
  `/tmp/openclaw/openclaw-YYYY-MM-DD.log` and `config-summary.json` into `logs/agent/`. Because the VM clears `/tmp` at each
  reboot and OpenClaw then restarts the *same file name*, each copy is stored as `openclaw-DATE.<fingerprint of the first
  line>.log`: a growing file is appended in place, a restarted file gets its own copy, nothing local is overwritten or
  deleted; a non-prefix difference is saved as `.conflict-<time>`. A VM whose `/tmp/openclaw` is unreadable gives a clear
  error with the HYR-10 hint instead of an empty file. Suggested cron: `7 * * * * .../scripts/pull_agent_logs.sh -q`
  (not installed by me).
- **Parser/analysis** `console/readers/agent_log.py`: events from real record shapes (tool starts with `totalMs`, models
  from `agent model:` lines, MCP connect failures, tool removed by policy, host freezes, Ollama preflight failures, agent
  failures, "looks like a tool call"); models attributed by the last model line; time-to-tool percentiles; greedy pairing
  of agent tool starts with desktop MCP requests within 20 s (desktop start = record time minus duration; verified on the
  real 2026-10-30 pair, 0.6 s apart); text-only days confirm a start but are never counted as MCP traffic.
- **API** `GET /api/v1/toolcalls/summary?days=` (totals, per model, per day, time-to-tool samples, flags, desktop side,
  sources and age). **UI** `pages/ToolCalls.tsx` + `TimeToToolChart.tsx` (accessible SVG scatter, nice axis ticks).
- **Demo data** rewritten to tell the story: 14 days of consistent query logs (text + JSONL) and agent logs; a small model
  that writes calls as text for 7 days, then a larger model; one morning with the MCP server down. The demo clock is now
  frozen (`ConsoleConfig.now()`), so the demo never turns stale. The "looks like" WARN record and the milestone
  `model_response_received` in the demo are invented.
- **Triage:** C6 (copies fresh, offers to pull; `PULL_CMD`, `AGENT_DIR`, `PULL_MAX_HOURS`), C8 (config summary on the VM
  recent). C7 (log readable) already existed.
- **Docs:** console guide section, runbooks `tool-never-called.md` and `mcp-server-down.md`, README.
- **Tests:** 184 pass: 11 parser/analysis (incl. scrubbed real fixtures in `tests/fixtures/agent/`), 9 API, 8 pull-script
  (fake ssh: idempotence, growth, VM reboot, prefix, permission error, dry run, quiet, wrapper), 2 triage, 11 browser.
- **Not achieved:** open question 9 (reproduce the failure-case message with a small model). It needs the agent model
  changed on the bot VM, which this read-only access cannot do, and the VM was unreachable ("No route to host") for part of
  the session. Detection is based on the documented message; the rate of turns without a tool start is the fallback.
  Real-data check used the two real log copies already on hand (1 turn: the 2026-10-30 router question, 50.2 s to tool).

### M5 as built (2026-10-31)
- **`console/queries.py`** + `GET /api/v1/queries/stats?days=&slow_seconds=` and `GET /api/v1/queries/slow?kind=slow|no_result|error&days=&limit=`.
  Metrics and definitions are in `Doc/console-guide.md` (Page 3) and the module docstring. System prompts (`### Task:`) are counted
  separately and excluded everywhere (plan note under FR-3.4).
- **Reader fix found with real data:** `read_day` preferred the JSONL file over the text log, but a JSONL file starts when the
  engine was last (re)started (2026-10-30: 23:55), which would have hidden the rest of that day. It now takes text-log events
  from before the first JSONL record and the JSONL after it. Page 4 uses the same reader and benefits.
- **Masking (T-PRIV-2):** `mask_text` (stable short hash, so recurrence survives); the test found that unquoted paths in error
  messages leaked, so `mask_message` now also masks bare absolute paths (URLs are kept).
- **UI:** `pages/QueryAnalytics.tsx`, `components/QueryCharts.tsx` (stacked bars per day, median/p95 lines with the slow line;
  accessible SVG with titles and legends). The `Planned` placeholder component is gone: all four pages exist.
- **Tests:** 200 pass (+16): hand-computed fixture month, independent count on the generated month, text/JSONL agreement,
  partial-day merge, threshold override, recurring terms, lists, window and validation, empty logs, masking, 6 browser tests.
- **Percentiles** use nearest rank, so on few points a median is one of the two middle values.
