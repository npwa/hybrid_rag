# HYR-04: Office lock files (`~$*`) are not excluded from ingest

- **Severity:** Low
- **Status:** Open
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
