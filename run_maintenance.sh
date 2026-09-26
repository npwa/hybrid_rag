#!/usr/bin/env bash
# Step 8 maintenance loop — chain ingest -> chunk -> index, log the result, email a report.
#
# Usage:
#   ./run_maintenance.sh            # normally invoked daily from cron
#
# See Doc/step-8-requirements.md. Each stage is already independently incremental
# (only new/changed/removed files do any work), so a run with nothing to do is cheap.
#
# Behavior:
#   - One run at a time: guarded by flock. A run started while another is still going
#     does not touch any stage; it fails immediately and reports that by email.
#   - Fail-fast: stages depend on each other's output, so a nonzero exit from one stage
#     skips the rest of that run.
#   - Every run — success, failure, or blocked by the lock — appends a summary to
#     logs/maintenance.log (append-only, no rotation) and sends one email.
#
# Overridable for testing (all optional):
#   MAINTENANCE_CONFIG     maintenance config (default config/maintenance_config.yaml)
#   INGEST_CONFIG / CHUNK_CONFIG / INDEX_CONFIG   per-stage configs (defaults in config/)
#   MAINTENANCE_MAIL_CMD   mail command taking `-s SUBJECT ADDRESS` args + body on stdin
#   MAINTENANCE_LOG        summary log path (default logs/maintenance.log)
#   MAINTENANCE_LOCK       lock file path (default .maintenance.lock)

set -u -o pipefail

# cron starts jobs with a minimal environment and an arbitrary working directory: no
# activated venv, no interactive PATH. Resolve everything from this script's own
# location and call the venv's interpreter by absolute path.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1
PY="$PROJECT_DIR/.venv/bin/python3"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

MAINTENANCE_CONFIG="${MAINTENANCE_CONFIG:-config/maintenance_config.yaml}"
INGEST_CONFIG="${INGEST_CONFIG:-config/ingest_config.yaml}"
CHUNK_CONFIG="${CHUNK_CONFIG:-config/chunk_config.yaml}"
INDEX_CONFIG="${INDEX_CONFIG:-config/index_config.yaml}"
MAIL_CMD="${MAINTENANCE_MAIL_CMD:-mail}"
LOG="${MAINTENANCE_LOG:-logs/maintenance.log}"
LOCKFILE="${MAINTENANCE_LOCK:-.maintenance.lock}"
case "$LOG" in /*) ;; *) LOG="$PROJECT_DIR/$LOG" ;; esac
case "$LOCKFILE" in /*) ;; *) LOCKFILE="$PROJECT_DIR/$LOCKFILE" ;; esac

mkdir -p "$(dirname "$LOG")"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$LOG"; }

fmt_duration() {  # seconds -> "1h02m03s" / "4m12s" / "37s"
    local s=$1
    if   (( s >= 3600 )); then printf '%dh%02dm%02ds' $((s/3600)) $((s%3600/60)) $((s%60))
    elif (( s >= 60 ));   then printf '%dm%02ds' $((s/60)) $((s%60))
    else                       printf '%ds' "$s"; fi
}

# Flat "key: value" config read (see the example config for why this isn't a YAML parse).
config_value() {
    [[ -f "$MAINTENANCE_CONFIG" ]] || return 0
    sed -n "s/^$1:[[:space:]]*\([^#]*[^#[:space:]]\).*$/\1/p" "$MAINTENANCE_CONFIG" | head -1
}
REPORT_EMAIL="$(config_value report_email)"

# Field extractor for a stage's "RUN_SUMMARY stage=... key=value ..." line.
field() { grep -o " $2=[^ ]*" <<<"$1" | head -1 | cut -d= -f2; }

send_report() {  # send_report SUBJECT BODY
    log "REPORT subject: $1"
    if [[ -z "$REPORT_EMAIL" ]]; then
        log "WARNING no report_email in $MAINTENANCE_CONFIG — no email sent"
        return 1
    fi
    if ! printf '%s\n' "$2" | "$MAIL_CMD" -s "$1" "$REPORT_EMAIL"; then
        log "ERROR sending report email to $REPORT_EMAIL via '$MAIL_CMD' failed"
        return 1
    fi
    log "report emailed to $REPORT_EMAIL"
}

START_EPOCH=$(date +%s)
START_HUMAN="$(date '+%Y-%m-%d %H:%M:%S')"

# --- Overlap protection ---------------------------------------------------------------
# flock on a held file descriptor: atomic, and released automatically if the holder dies
# without cleaning up, so there's no stale-PID logic to get wrong.
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    log "=== maintenance run BLOCKED: a previous run is still in progress ==="
    send_report "[hybrid-rag maintenance] FAILED — previous run still in progress" \
"Maintenance run at $START_HUMAN did not start.

A previous maintenance run is still holding the lock ($LOCKFILE). No stage
was run. This is expected only if the previous run has been going longer than the
schedule interval; otherwise check for a hung process (ps aux | grep run_)."
    exit 1
fi

log "=== maintenance run start ==="
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

STATUS="OK"
FAILED_STAGE=""
STAGE_LINES=""
STAGE_LOGS=""
declare -A SUMMARY

run_stage() {  # run_stage NAME SCRIPT CONFIG
    local name=$1 script=$2 config=$3 out="$WORK_DIR/$1.out" t0 rc elapsed summary
    t0=$(date +%s)
    log "stage $name: start ($script --config $config)"
    "$PY" "$script" --config "$config" >"$out" 2>&1
    rc=$?
    elapsed=$(( $(date +%s) - t0 ))
    summary="$(grep '^RUN_SUMMARY ' "$out" | tail -1)"
    SUMMARY[$name]="$summary"
    STAGE_LOGS+="  $name: $(grep '^Log: ' "$out" | tail -1 | sed 's/^Log: //')"$'\n'
    if (( rc != 0 )); then
        log "stage $name: FAILED (exit $rc, $(fmt_duration $elapsed))"
        log "stage $name: last output lines follow"
        tail -n 20 "$out" | sed 's/^/    | /' >> "$LOG"
        STAGE_LINES+="$name: FAILED (exit $rc, $(fmt_duration $elapsed))"$'\n'
        STAGE_LINES+="$(tail -n 15 "$out" | sed 's/^/    | /')"$'\n'
        return "$rc"
    fi
    log "stage $name: ok ($(fmt_duration $elapsed)) ${summary#RUN_SUMMARY }"
    STAGE_LINES+="$name: ok ($(fmt_duration $elapsed)) ${summary#RUN_SUMMARY stage=$name }"$'\n'
    return 0
}

if   ! run_stage ingest run_ingest.py "$INGEST_CONFIG"; then STATUS="FAILED"; FAILED_STAGE="ingest"
elif ! run_stage chunk  run_chunk.py  "$CHUNK_CONFIG";  then STATUS="FAILED"; FAILED_STAGE="chunk"
elif ! run_stage index  run_index.py  "$INDEX_CONFIG";  then STATUS="FAILED"; FAILED_STAGE="index"
fi

ELAPSED=$(( $(date +%s) - START_EPOCH ))
DURATION="$(fmt_duration $ELAPSED)"
END_HUMAN="$(date '+%Y-%m-%d %H:%M:%S')"

# Headline counts are file-level, from ingestion (the stage that sees the source tree).
ING="${SUMMARY[ingest]:-}"
if [[ -n "$ING" ]]; then
    COUNTS="+$(field "$ING" added) ~$(field "$ING" updated) -$(field "$ING" removed)"
else
    COUNTS="no ingest result"
fi

if [[ "$STATUS" == "OK" ]]; then
    SUBJECT="[hybrid-rag maintenance] OK — $DURATION — $COUNTS"
else
    SUBJECT="[hybrid-rag maintenance] FAILED at $FAILED_STAGE stage — $DURATION"
fi

log "=== maintenance run end: $STATUS in $DURATION ($COUNTS) ==="

BODY="Status:   $STATUS${FAILED_STAGE:+ (at $FAILED_STAGE stage; later stages skipped)}
Started:  $START_HUMAN
Finished: $END_HUMAN
Duration: $DURATION
Files:    ${COUNTS}  (added / updated / removed, this run)

Stages:
$STAGE_LINES
Maintenance log: $LOG
Per-stage logs:
$STAGE_LOGS"

send_report "$SUBJECT" "$BODY"

[[ "$STATUS" == "OK" ]]
