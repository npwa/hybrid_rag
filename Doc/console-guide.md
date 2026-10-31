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

## Pages not built yet
Query explorer (M3), Tool-call monitor (M4), Query analytics (M5): the tabs exist and say so.

## API (for scripts)
Interactive docs at `/docs`; snapshot in `Doc/api/openapi.json`. Page 1 uses `/api/v1/health`,
`/api/v1/index/summary`, `/api/v1/index/failures`, `/api/v1/index/causes`, `/api/v1/maintenance/runs`.

## Privacy
Set `mask_queries: true` in the console config to replace file names in the problem-file list by short hashes (the
extension is kept) and to hide paths inside error messages. The numbers stay the same.
