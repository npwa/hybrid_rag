# HYR-10: `ragr` loses read access to today's OpenClaw log (ACL mask reset by chmod 600)

- **Severity:** Medium (breaks triage.sh log checks and the planned tool-call monitor)
- **Status:** Open (fix agreed: 5-minute cron `setfacl`; pending install on the VM)
- **Component:** `/tmp/openclaw/openclaw-YYYY-MM-DD.log` on npabot-u24; `scripts/triage.sh`

## Impact
`ragr` can read a log shortly after it is created, then loses access: on 2026-10-30
`cat /tmp/openclaw/openclaw-2026-10-30.log` returned "Permission denied" although
`ragr` has an ACL entry. The log checks in `triage.sh` (Signal errors, MCP connect
failures, tool events) and the step-9 tool-call monitor cannot see the current day.

## Description
Observed at 21:20 PDT: the file is `-rw-------+ nick nick` with ACL
`user:ragr:r--  #effective:---` and `mask::---`. Earlier the same file was `-rw-r-----+`
with an effective `r--`. OpenClaw sets the file mode to 600 (at creation and again later
in the day); on a file with an ACL, `chmod` changes the ACL **mask**, so the named-user
entry for `ragr` becomes ineffective even though it is still listed. The directory's
default ACL does not help because the mask is reset by the later chmod.

Before this was noticed, `triage.sh` reported "no MCP connect failures logged today" when
the read had failed (grep over empty input). That is fixed: it now warns and tells the
operator what to do.

## Proposed fix
1. Short term (VM, as `nick`; agreed approach): add to crontab next to the config-summary job:
   `*/5 * * * * setfacl -m m::r /tmp/openclaw/openclaw-*.log 2>/dev/null`
   This restores the ACL mask within 5 minutes of any chmod. Known gap: up to 5 minutes
   after OpenClaw resets the mode (for example just after midnight, when the new day's
   file is created) `ragr` cannot read the log, and `triage.sh` shows its "cannot read
   today's OpenClaw log" warning. Acceptable for daily pulls; use `* * * * *` if it
   becomes a nuisance. The glob also covers `openclaw-dev-*.log`.
2. Better: have OpenClaw log to a directory with a stable policy, or let a `nick` cron job
   copy each log to `/tmp/openclaw/export/` (mode 640 with `ragr` ACL) and read the copy.
   A copy also helps retention (`/tmp` is volatile).
3. Pull the log to the desktop daily (step-9 §7) so the history survives reboots.

## Acceptance
`ssh ragr@npabot-u24 cat /tmp/openclaw/openclaw-$(date +%F).log` works at any time of day,
including after a gateway restart, and `scripts/triage.sh 3` shows gateway events without
the permission warning.

## Related
HYR-09 (`ragr` account hardening), `Doc/step-9-requirements.md` §7.
