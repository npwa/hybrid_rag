#!/usr/bin/env bash
# Copy the OpenClaw agent logs (and the secret-free config summary) from the bot VM into logs/agent/, read-only.
#
# Usage:  scripts/pull_agent_logs.sh [-n|--dry-run] [-q|--quiet] [-h|--help]
#   -n, --dry-run  show what would be copied; write nothing
#   -q, --quiet    print only problems (for cron)
# Exit status: 0 = ok (including "nothing new"), 1 = the VM or a log could not be read.
#
# The VM keeps logs in /tmp/openclaw/openclaw-YYYY-MM-DD.log and /tmp is cleared at every VM reboot (about daily,
# 21:52), after which OpenClaw starts a NEW file with the same name. So each copy is stored under a name that includes
# a fingerprint of the file's first line: logs/agent/openclaw-YYYY-MM-DD.<fp>.log. A later pull of the same incarnation
# only adds the new bytes; a restarted file gets its own copy; nothing local is ever overwritten or deleted.
# The dev instance's logs (openclaw-dev-*) are not copied.
#
# Same access as scripts/triage.sh: user ragr (read-only), key ~/.ssh/claude/id_claude_ed25519.
# BOT_WRAPPER=1 uses the forced-command verbs (logs, log DATE, config) instead of plain read-only commands.
# Cron suggestion (hourly, so little is lost when /tmp is cleared):   7 * * * * /path/to/scripts/pull_agent_logs.sh -q
#
# Overridable: BOT_HOST (npabot-u24) BOT_USER (ragr) BOT_KEY (~/.ssh/claude/id_claude_ed25519)
#              DEST (logs/agent under the project) REMOTE_DIR (/tmp/openclaw)
set -u
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
PROJECT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
BOT_HOST="${BOT_HOST:-npabot-u24}"; BOT_USER="${BOT_USER:-ragr}"
BOT_KEY="${BOT_KEY:-$HOME/.ssh/claude/id_claude_ed25519}"
DEST="${DEST:-$PROJECT_DIR/logs/agent}"; REMOTE_DIR="${REMOTE_DIR:-/tmp/openclaw}"
DRY=0; QUIET=0
for a in "$@"; do case "$a" in
  -n|--dry-run) DRY=1 ;; -q|--quiet) QUIET=1 ;;
  -h|--help) sed -n '2,/^set -u/p' "$SCRIPT_PATH" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown argument: $a (try --help)" >&2; exit 2 ;; esac; done

say() { [ "$QUIET" = 1 ] || echo "$*"; }
rssh() { ssh -n -F /dev/null -i "$BOT_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 "$BOT_USER@$BOT_HOST" "$@"; }

mkdir -p "$DEST" 2>/dev/null || { echo "cannot create $DEST" >&2; exit 1; }
exec 9>"$DEST/.pull.lock"; flock -n 9 || { say "another pull is running"; exit 0; }

errs=0; new_files=0; grown=0; same=0; bytes=0
if [ "${BOT_WRAPPER:-0}" = 1 ]; then LIST="logs"; else LIST="ls -1 $REMOTE_DIR"; fi
listing=$(rssh "$LIST" 2>&1); rc=$?
if [ $rc -ne 0 ]; then
  if [[ "$listing" == *"cannot open directory"* || "$listing" == *"cannot access"* ]]; then
    echo "cannot read $REMOTE_DIR on $BOT_HOST: ${listing:0:160}. The /tmp/openclaw ACL for $BOT_USER was probably lost at a VM reboot (see Doc/Issues/HYR-10.md)." >&2
  else echo "cannot reach $BOT_HOST: ${listing:0:200}" >&2; fi
  exit 1
fi
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fetch_remote() {   # fetch_remote <remote file name> <out file>
  local f="$1" out="$2"
  if [ "${BOT_WRAPPER:-0}" = 1 ]; then
    local d="${f#openclaw-}"; d="${d%.log}"; rssh "log $d" > "$out" 2>"$tmp/err"
  else rssh "cat $REMOTE_DIR/$f" > "$out" 2>"$tmp/err"; fi
}
while IFS= read -r f; do
  [[ "$f" =~ ^openclaw-[0-9]{4}-[0-9]{2}-[0-9]{2}\.log$ ]] || continue          # excludes openclaw-dev-*, config-summary, junk
  if ! fetch_remote "$f" "$tmp/cur"; then echo "cannot read $f: $(head -c 200 "$tmp/err")" >&2; errs=$((errs+1)); continue; fi
  [ -s "$tmp/cur" ] || continue
  fp=$(head -n1 "$tmp/cur" | sha1sum | cut -c1-8)      # first line: stable while the file grows, new after a VM reboot
  local_name="${f%.log}.$fp.log"; dst="$DEST/$local_name"
  rsize=$(stat -c %s "$tmp/cur")
  if [ ! -e "$dst" ]; then
    say "new     $local_name ($rsize bytes)"; new_files=$((new_files+1)); bytes=$((bytes+rsize))
    if [ "$DRY" != 1 ]; then cp "$tmp/cur" "$dst.part" && mv "$dst.part" "$dst"; fi
  else
    lsize=$(stat -c %s "$dst")
    if [ "$rsize" -gt "$lsize" ] && cmp -s -n "$lsize" "$dst" "$tmp/cur"; then
      say "grown   $local_name (+$((rsize-lsize)) bytes)"; grown=$((grown+1)); bytes=$((bytes+rsize-lsize))
      [ "$DRY" = 1 ] || tail -c +"$((lsize+1))" "$tmp/cur" >> "$dst"
    elif [ "$rsize" -eq "$lsize" ] && cmp -s "$dst" "$tmp/cur"; then same=$((same+1))
    elif [ "$rsize" -lt "$lsize" ] && cmp -s -n "$rsize" "$dst" "$tmp/cur"; then same=$((same+1))   # remote is a shorter prefix: keep ours
    else
      echo "conflict: $f differs from the local copy $local_name (not a prefix); saved as $local_name.conflict-$(date +%s)" >&2
      [ "$DRY" = 1 ] || cp "$tmp/cur" "$dst.conflict-$(date +%s)"; errs=$((errs+1))
    fi
  fi
done <<< "$listing"

# config summary (no secrets; refreshed on the VM every 5 minutes)
if [ "${BOT_WRAPPER:-0}" = 1 ]; then cs=$(rssh config 2>/dev/null); else cs=$(rssh "cat $REMOTE_DIR/config-summary.json" 2>/dev/null); fi
if [ -n "$cs" ] && echo "$cs" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
  [ "$DRY" = 1 ] || printf '%s\n' "$cs" > "$DEST/config-summary.json"
else say "config-summary.json not available (cron job on the VM, see HYR-10)"; fi

note=""; [ "$DRY" = 1 ] && note=" (dry run, nothing written)"
say "done: $new_files new, $grown grown, $same unchanged, $bytes bytes$note"
[ "$errs" -eq 0 ]
