# HYR-06: Unconvertible and low-confidence-OCR files reduce coverage

- **Severity:** Low-Medium
- **Status:** Open
- **Component:** ingest / OCR (`ocr_low_confidence`, `failed` statuses)

## Impact
Of about 2,534 files, 509 failed conversion and 75 were OCR'd below the 40.0
confidence threshold, so some content is absent or noisy in the index. Part of
the 509 is expected (images with no text, lock files, see HYR-04; permission
errors, see HYR-03), but the remainder is unreviewed.

## Description
The 26 document failures are 22 PDF, 2 DOCX, 1 XLSX and 1 TXT, including at
least one damaged PDF. Low-confidence OCR text is indexed with `ocr_confidence`
metadata but is not re-scanned. `convert_to_md.sh` also has an xargs quoting bug
(e.g. the path `Pool/README`). Details are in `logs/failed_files_report.tsv`.

## Proposed fix
1. Triage the 26 document failures individually: repair or re-export the
   damaged PDF; fix the quoting bug in `convert_to_md.sh`.
2. Re-run OCR on the 75 low-confidence files with a higher DPI or different
   settings; accept or drop results by threshold.
3. Add a summary of remaining failures by cause to the maintenance report.

## Acceptance
Every failed document file has a recorded cause, and either converts or is
deliberately excluded.
