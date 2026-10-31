# PM-06: NFS "permission denied" after uid mapping changes

**Date:** not recorded (before 2026-10-30; tracked as HYR-03). **Severity:** Medium.

## Summary
After the NFSv4 export from `mars` was set up, the desktop user (uid 1001, mapped to `maryse` on mars) could not read part of
`/mnt/mars/nick`. About 15 documents were therefore never indexed.

## Impact
Questions about those documents get no answer. They are part of the failed files of the last full ingest (509 failed files overall,
of which these are one cause; see the console's "Index health" causes table for the live number).

## Timeline
- Mount worked but many files returned "Permission denied".
- `manage-gids` was disabled on mars: the mount became readable.
- A remaining set of files has modes without group read, and one file with mode 640 is still unreadable (an ACL or extended attribute
  is suspected). Open as HYR-03.

## Detection
Ingest failures with error messages mentioning permission, listed in `logs/failed_files_report.tsv`. The console now classifies them
as the cause "permission denied".

## Root cause
Identity mapping between the two hosts changed what the desktop user is allowed to read, and some files never granted group read.

## Fix
Applied: `manage-gids` off. Pending (HYR-03): `chmod g+r` on the listed files on mars and a check of ACLs for the 640 file.

## Prevention
- Console: the "Problem files" table filters by cause; a permission-denied count above zero links to HYR-03.
- Triage: the maintenance check reports a missing source mount separately from conversion failures.
- Keep source permissions in mind when adding folders to the corpus.
