# HYR-11: `convert_to_md.sh` aborts on text with an apostrophe before a colon

- **Severity:** Low (one file affected: `Pool/README`)
- **Status:** Fixed in code on branch `console` (2026-11-01); the file converts at the next ingest run after the retry rule below
- **Component:** `convert_to_md.sh` (README/TODO conversion)

## Impact
A README whose text contains a line like `Here's a detailed breakdown of the causes:` fails conversion, so the file has no extracted
text and is not searchable. `Pool/README` was recorded as `failed` with `convert_to_md.sh exited 1: xargs: unmatched single quote`.
It was the only file with this error in the manifest.

## Description
The script trims whitespace by piping through `xargs` (key of "Key: value" lines, status lines, rag-tags). `xargs` treats quote
characters as special, so an unmatched `'` or `"` makes it exit 1; the script runs with `set -euo pipefail`, so the whole conversion stops.
The trigger is any line containing a colon and an unmatched quote before the first colon.

## Resolution (2026-11-01)
`xargs` replaced by a `trim` function (`sed`, collapses and strips whitespace) at the three places it was used. Tests:
`tests/test_convert_to_md.py` (fails on the old script, passes on the new one); `Pool/README` converted by hand to a temporary directory
(259 lines, rc 0). Verify after the next maintenance run that `Pool/README.md` exists under `extracted_text/` and the file is `extracted`.

## Second part found 2026-11-01: failed READMEs were never retried
After the first fix, a maintenance run still left `Pool/README` as `failed`: ingest keeps the stored result of any file whose content hash is
unchanged, including failures, so the fixed converter never ran. `ingest/pipeline.py` now retries a failed README/TODO on every run (cheap,
and the converter script can change); other failures (e.g. OCR produced no text) are still not re-run. Test: `test_failed_readme_is_retried_...`.

## Related
HYR-04 (other file-filter fix in the same stage).
