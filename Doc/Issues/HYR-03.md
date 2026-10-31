# HYR-03: Permission-denied documents on mars are not ingested

- **Severity:** Medium
- **Status:** Open (NFS `manage-gids` fix applied; file modes still block reads)
- **Component:** ingest / `/mnt/mars/nick` (NFSv4 from mars)

## Impact
About 15 documents are missing from the index because they cannot be read, so
questions about their content get no answer. They are part of the 509 files
that failed to convert in the last full ingest.

## Description
The desktop user (uid 1001) maps to `maryse` on mars. After disabling
`manage-gids` on mars the mount is readable, but the affected files have
restrictive modes (no group read). One further file with mode 640 is still
unreadable, which suggests an ACL or extended attribute. The full list is in
`logs/failed_files_report.tsv` (not committed).

## Proposed fix
1. On mars, run `chmod g+r` on the listed files (or fix the owning group) after
   reviewing the list.
2. For the 640 file, check `getfacl` / `getfattr` on mars and correct it.
3. Re-run the maintenance loop; confirm the files move from `failed` to
   `extracted`.
4. Optionally have the ingest log permission errors under a distinct status so
   they are not mixed with conversion failures.

## Acceptance
`logs/failed_files_report.tsv` has zero permission-denied entries after the next
maintenance run.
