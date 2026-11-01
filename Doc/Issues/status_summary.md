# Issue status summary

Generated 2026-11-01 14:02 by `Doc/Issues/mk_report.sh` from the ticket files in this folder. Do not edit by hand.

## Overview

- 11 tickets: **7 open**, **1 fixed and waiting for verification**, **3 closed**.
- Highest severity still open or unverified: **High**.
- By severity (open and to-verify): High 1, Medium 2, Low-Medium 2, Low 3.
- "Fixed, waiting for verification" means the change exists but the ticket's acceptance check has not been recorded as passed; set its status to Closed once it has.

## Open (most severe first)

| ID | Severity | Title | Note |
|---|---|---|---|
| [HYR-02](HYR-02.md) | Medium | Dense search has no ANN index (brute-force scan) | - |
| [HYR-10](HYR-10.md) | Medium | `ragr` loses read access to OpenClaw logs (ACL mask reset by chmod 600; directory ACL lost on VM reboot) | fix agreed: cron restoring directory and file ACLs; installed by the owner on 2026-10-31, to be confirmed a... |
| [HYR-06](HYR-06.md) | Low-Medium | Unconvertible and low-confidence-OCR files reduce coverage | - |
| [HYR-09](HYR-09.md) | Low-Medium | Read-only log account `ragr` on npabot-u24 can run arbitrary commands | partially mitigated |
| [HYR-05](HYR-05.md) | Low | Stale "do not re-attempt" line in step-5 requirements on main | - |
| [HYR-07](HYR-07.md) | Low | Open WebUI HTTP server (`run_server.py`, port 8100) not running | only matters if the Open WebUI path is used |
| [HYR-08](HYR-08.md) | Low | Untracked junk files and missing .gitignore entries | - |

## Fixed, waiting for verification

| ID | Severity | Title | Note |
|---|---|---|---|
| [HYR-01](HYR-01.md) | High | MCP server has no service supervisor (manual start only) | Fixed in code on branch `console` (2026-11-01); installed and enabled by the owner (2026-11-01, lingering o... |

## Closed

| ID | Severity | Title | Note |
|---|---|---|---|
| [HYR-03](HYR-03.md) | Medium | Permission-denied documents on mars are not ingested | 2026-11-01; the files are readable and ingested |
| [HYR-04](HYR-04.md) | Low | Office lock files (`~$*`) are not excluded from ingest | 2026-11-01; verified by the owner |
| [HYR-11](HYR-11.md) | Low | `convert_to_md.sh` aborts on text with an apostrophe before a colon | 2026-11-01; verified by the owner |
