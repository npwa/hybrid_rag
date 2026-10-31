# Runbook: the index looks stale

**Shown as:** red banner "The index looks stale" on the Index health page; status header "Index STALE";
`scripts/triage.sh 5`. **Related:** `Doc/step-8-requirements.md`, HYR-10 (not related to the data, but the same cron host).

## What it means
The last *successful* index step (`stage index: ok` in `logs/maintenance.log`) is older than the threshold
(`stale_after_hours`, default 36 h because maintenance runs daily), or the last maintenance run ended FAILED.
New or changed documents may be missing from answers.

## Check
1. `scripts/triage.sh 5` shows the last runs, the last successful index and what it judged.
2. `tail -30 logs/maintenance.log`. Only the **last** `=== maintenance run end:` line decides the current state;
   older FAILED lines are history.
3. Was cron running? `grep CRON /var/log/syslog | tail` and `cat logs/maintenance_cron.log | tail`.
4. Is the source tree reachable? `ls /mnt/mars/nick | head` (NFS, see below).
5. Is Ollama up? `curl -s localhost:11434/api/tags | head -c 100` (the index step needs `nomic-embed-text`).

## Fix
- Run it now: `./run_maintenance.sh` (idempotent; only new/changed files are processed), or `scripts/triage.sh 5`
  and answer `y`.
- Source tree not readable (`Permission denied` or empty): see `Doc/Issues/HYR-03.md`; remount and re-run.
- Ollama down: `systemctl status ollama` (or start it), then re-run.
- "no ingest result" FAILED runs: usually the source mount is missing at cron time.

## Prevent
Keep the daily cron; the console and `triage.sh` both warn before the threshold matters.
