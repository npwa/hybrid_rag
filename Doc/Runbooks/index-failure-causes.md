# Runbook: why files did not index cleanly

**Shown as:** "Why files did not index cleanly" and "Problem files" on the Index health page. Each cause id below is
the `cause` value used by the API (`/api/v1/index/failures?cause=...`). Counts shown are from the development
corpus on 2026-10-31 and will change.

General check: `GET /api/v1/index/failures?cause=<id>` or the table filter; the full text of the error is the row's
tooltip. Re-running ingest (`./run_maintenance.sh`) re-tries failed files only when their content changed.

## `ocr_no_text`: Image or scan with no recognisable text (413)
Tesseract found no text (photos, drawings, blank scans). **Usually expected.** Nothing to fix unless the image should
contain text: then rescan at higher resolution. Ticket HYR-06.

## `ocr_below_threshold`: OCR confidence below the failure threshold (75)
Text was read but with confidence under 40.0, so it was not indexed. Check the original; consider a better scan or
retry OCR with other settings (HYR-06). Not a pipeline fault.

## `ocr_low_confidence`: Indexed, but OCR confidence is low (285)
Indexed with `ocr_confidence` stored (between the failure threshold and the high threshold). Answers from these files
may contain OCR errors. Review the worst ones on the page (sort by OCR conf.). HYR-06.

## `permission_denied`: Permission denied reading the file (15)
The desktop user cannot read the file over NFS (restrictive mode on the server, wrong group, ACL). See HYR-03.
Fix on the file server (`chmod g+r` after review, or fix the group/ACL), then re-run maintenance.

## `lock_file`: Office lock file `~$...` (3)
Temporary files from Word/Excel/PowerPoint. Since HYR-04 they are excluded at classification time, so they become
`skipped` on the next ingest run and drop out of this list. If one persists, check `exclude_prefixes` in
`config/ingest_config.yaml`.

## `damaged_file`: Damaged or unreadable file (2)
Corrupt PDF (malformed page tree), image that cannot be identified, or a broken Office package. Re-export or
repair the original (HYR-06).

## `conversion_error`: Conversion script error (1)
`convert_to_md.sh` failed (known xargs quoting bug for a path with a single quote). HYR-06.

## `encrypted`: Encrypted file (10)
Password-protected; the pipeline cannot read it. Remove the password if the content should be searchable.

## `empty_conversion`: Conversion produced almost no text (4)
LibreOffice conversion of an old `.doc`/`.xls` produced under 10 non-whitespace characters (known caveat). Convert
manually to `.docx`/`.xlsx` and re-ingest.

## `empty`: Empty file (1)
Zero bytes. Nothing to do.

## `other`: Other / unrecognised
The error text matched no known pattern. Read the message (row tooltip), fix or add a new cause in
`console/failures.py` and a test in `tests/test_page1_api.py`.
