# HYR-04: Office lock files (`~$*`) are not excluded from ingest

- **Severity:** Low
- **Status:** Closed (2026-11-01; verified by the owner)
- **Component:** ingest file filtering / `config/`

## Impact
Temporary lock files created by Word/Excel/PowerPoint (`~$name.docx` etc.) are
picked up as documents, fail conversion, and inflate the failed-file count
(part of the 509). They add noise to reports and triage.

## Description
The ingest scanner has no exclusion for names beginning with `~$` (and likewise
LibreOffice `.~lock.*#`). These files contain no document text and always fail.

## Proposed fix
Add `~$*` and `.~lock.*#` to the ingest exclude patterns (config-driven if an
exclude list exists, otherwise in the scanner). Mark any already-recorded lock
files as `skipped` in the manifest so they stop appearing as failures.

## Acceptance
A fresh scan records no `~$*` or `.~lock.*#` files as failed, and
`logs/failed_files_report.tsv` contains none.

## Resolution (2026-10-31)
`ingest/classify.py` now excludes names starting with a configured prefix (`exclude_prefixes`, default `["~$"]`,
optional in the config so older configs keep working; `.~lock.*#` was already excluded by the `#` suffix rule).
Tests: `tests/test_ingest_classify.py`. Files already recorded as `failed` (3 on the development corpus) become
`skipped` on the next ingest run (excluded files are upserted as skipped before the content check). Verify
after the next maintenance run that `GET /api/v1/index/failures?cause=lock_file` is empty, then close.

## Verification (2026-11-01)
Verified by the owner after a maintenance run (2026-11-01): no lock files remain among the failures.
