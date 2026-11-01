#!/usr/bin/env bash
# Acceptance step 5.8-4: prove the running console changes nothing. Checksums manifest.db (+ -wal/-shm) and every file
# under lancedb/, exercises every GET endpoint and the explorer, then checksums again.
# Usage: scripts/verify_readonly.sh [PORT]     Exit 0 if identical, 1 if anything changed.
# Run it when no ingest/maintenance job is running, otherwise those jobs' own writes show up as differences.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PORT="${1:-${CONSOLE_PORT:-8300}}"; BASE="http://127.0.0.1:$PORT/api/v1"
snap() { find manifest.db* lancedb -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum; }
curl -sf -m 5 "$BASE/health" >/dev/null || { echo "console not answering on :$PORT"; exit 2; }
if pgrep -f 'run_(ingest|index|maintenance)' >/dev/null; then echo "an ingest/index job is running; try again when it finishes"; exit 2; fi
before=$(snap)
n=0
for p in $(curl -s "http://127.0.0.1:$PORT/openapi.json" | python3 -c '
import json,sys
for path,ops in json.load(sys.stdin)["paths"].items():
    if "get" in ops and "{" not in path: print(path)'); do
  curl -s -o /dev/null -m 60 "http://127.0.0.1:$PORT$p"; n=$((n+1))
done
curl -s -o /dev/null -m 120 -X POST -H 'content-type: application/json' -d '{"query":"read-only verification"}' "$BASE/explore"
after=$(snap)
files=$(printf '%s\n' "$before" | wc -l)
if [ "$before" = "$after" ]; then echo "[ OK ] $files files unchanged after $n GET endpoints and one explore"; exit 0
else echo "[FAIL] data changed while the console was in use:"; diff <(echo "$before") <(echo "$after") | head; exit 1; fi
