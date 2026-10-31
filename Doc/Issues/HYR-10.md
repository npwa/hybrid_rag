# HYR-10: `ragr` loses read access to OpenClaw logs (ACL mask reset by chmod 600; directory ACL lost on VM reboot)

- **Severity:** Medium (breaks triage.sh log checks and the planned tool-call monitor)
- **Status:** Open (fix agreed: cron restoring directory and file ACLs; installed by the owner on 2026-10-31, to be confirmed across a reboot)
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

## Second cause found 2026-10-31: the directory ACL is lost on reboot
The VM reboots daily at about 21:52 (uptime was 2026-10-29 21:52 and 2026-10-30 21:52). `/tmp` is cleared
and OpenClaw recreates `/tmp/openclaw` as `drwx------ nick nick` with no ACL entries, so `ragr` cannot even
list or enter it: every file under it, including `config-summary.json`, becomes unreadable. A `setfacl` on the
log files alone cannot help (file ACLs are irrelevant when the directory denies traversal). Symptoms in
`triage.sh`: "cannot read today's OpenClaw log" and "cannot compare: the config summary is unreadable".
Recovery by hand, as `nick`:

    setfacl -m u:ragr:rx /tmp/openclaw
    setfacl -d -m u:ragr:r /tmp/openclaw
    setfacl -m u:ragr:r,m::r /tmp/openclaw/*.log /tmp/openclaw/config-summary.json

Separate effect, not a permission problem: just after local midnight the new day's log does not exist until
OpenClaw writes its first line; `triage.sh` now falls back to the newest `openclaw-20*.log`.

## Proposed fix
1. Short term (VM, as `nick`; installed by the owner): one cron entry that restores the directory ACL, the default
   ACL for new files, and the mask on existing files:
   `*/5 * * * * setfacl -m u:ragr:rx /tmp/openclaw && setfacl -d -m u:ragr:r /tmp/openclaw && setfacl -m u:ragr:r,m::r /tmp/openclaw/*.log /tmp/openclaw/config-summary.json 2>/dev/null`
   Known gaps: up to 5 minutes after a reboot or after OpenClaw resets a file mode `ragr` cannot read (use
   `* * * * *` if it becomes a nuisance); the glob also covers `openclaw-dev-*.log`; if no `*.log` matches the
   command prints an error that is discarded. Add `@reboot sleep 60; <same commands>` to shorten the post-reboot gap.
2. Better: have OpenClaw log to a directory with a stable policy, or let a `nick` cron job
   copy each log to `/tmp/openclaw/export/` (mode 640 with `ragr` ACL) and read the copy.
   A copy also helps retention (`/tmp` is volatile).
3. Find out why the VM reboots daily at about 21:52 (cron, libvirt schedule or OS update policy) and whether it is
   intended; if not, removing it also stops the log history from being lost.
4. Pull the log to the desktop daily (step-9 §7) so the history survives reboots.

## Acceptance
`ssh ragr@npabot-u24 cat /tmp/openclaw/openclaw-$(date +%F).log` works at any time of day,
including after a gateway restart and after a VM reboot (within the cron interval), and `scripts/triage.sh 3` shows gateway events without
the permission warning.

## Related
HYR-09 (`ragr` account hardening), `Doc/step-9-requirements.md` §7.

## Update 2026-10-31: desktop-side copy
`scripts/pull_agent_logs.sh` (step 9, M4) now copies the logs to `logs/agent/` read-only and keeps each VM incarnation of a
day's file separately, so reboots no longer lose history that was already pulled. It still needs the directory ACL to be
readable at pull time; with a daily reboot at about 21:52 an hourly pull (cron `7 * * * *`) loses at most the last hour.
