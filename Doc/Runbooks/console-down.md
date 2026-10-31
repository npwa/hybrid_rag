# Runbook: the console is not reachable

**Shown as:** the page cannot load, or the red bar "Cannot reach the console API"; `scripts/triage.sh 10` reports
"nothing listening on port 8300". The console is optional: the Signal path does not depend on it.

## Check
- `scripts/triage.sh 10` (listening? API healthy? read-only proof? data sources?).
- `ss -ltn | grep 8300`; `tail logs/console.out`.
- Web page blank but API fine: `console/web/dist` missing. Build it: `cd console/web && npm install && npm run build`.

## Fix
- Start it: `nohup .venv/bin/python run_console.py >> logs/console.out 2>&1 &` (or answer `y` in `triage.sh 10`).
- Port busy: another instance is running; stop that one (by PID) first.
- HTTP 500 with `internal_error`: the cause is in `logs/console.out`; a missing or locked data file is reported as 503 `source_unavailable`
  with the path.

## Prevent
A systemd `--user` unit is planned (milestone M7).
