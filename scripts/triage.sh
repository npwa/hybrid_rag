#!/usr/bin/env bash
# Interactive triage menu for the Signal -> OpenClaw (npabot-u24) -> MCP (this desktop) chain.
#
# Usage:  scripts/triage.sh [-y|--yes] [CHOICE...]
#   -y, --yes   answer "yes" to every "apply the fix?" prompt (for use from other scripts)
#   CHOICE      menu number(s) to run non-interactively, then exit (e.g. `triage.sh -y 1 7`).
#               With -y and no CHOICE, runs all quick checks (menu option 9) and exits.
#   -h, --help  show this help
# Exit status in non-interactive mode: 0 if no check FAILed, 1 otherwise.
# Color is used only when stdout is a terminal (and NO_COLOR is unset).
#
# Every check is read-only. Where there is a known, safe fix the script offers it with
# "apply the fix? (y/N)" and only runs it on an explicit y. Fixes that change the remote
# VM's state or config are never automatic; those are printed as instructions.
#
# Overridable (optional):
#   BOT_HOST (default npabot-u24)   BOT_USER (default nick)
#   BOT_KEY  (default ~/.ssh/claude/id_claude_ed25519)
#   MCP_PORT (default 8200)         BOT_VM (libvirt domain, default npa-u24)

set -u
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

BOT_HOST="${BOT_HOST:-npabot-u24}"
BOT_USER="${BOT_USER:-nick}"
BOT_KEY="${BOT_KEY:-$HOME/.ssh/claude/id_claude_ed25519}"
BOT_VM="${BOT_VM:-npa-u24}"
MCP_PORT="${MCP_PORT:-8200}"
TOOL="hybrid-rag__ask_documents"
PY="$PROJECT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3

ASSUME_YES=0
FAILS=0
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_OK=$'\e[32m'; C_BAD=$'\e[31m'; C_WARN=$'\e[33m'; C_OFF=$'\e[0m'
else
  C_OK=; C_BAD=; C_WARN=; C_OFF=
fi

ok()   { printf '  [%s OK %s] %s\n' "$C_OK" "$C_OFF" "$*"; }
bad()  { FAILS=$((FAILS+1)); printf '  [%sFAIL%s] %s\n' "$C_BAD" "$C_OFF" "$*"; }
warn() { printf '  [%sWARN%s] %s\n' "$C_WARN" "$C_OFF" "$*"; }
info() { printf '         %s\n' "$*"; }
hdr()  { printf '\n== %s ==\n' "$*"; }

confirm() {  # confirm "description" -> 0 only on explicit y/Y (or always with -y)
  if [ "$ASSUME_YES" = 1 ]; then echo "  -> $1 apply the fix? (y/N) y  [--yes]"; return 0; fi
  local a; read -r -p "  -> $1 apply the fix? (y/N) " a
  [[ "$a" == [yY] ]]
}

bot_ssh() {  # read-only remote command on the bot VM
  ssh -n -F /dev/null -i "$BOT_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o ConnectTimeout=5 "$BOT_USER@$BOT_HOST" "$@" 2>&1
}

bot_log() { echo '/tmp/openclaw/openclaw-$(date +%F).log'; }

mcp_listening() { ss -ltn 2>/dev/null | grep -q ":$MCP_PORT "; }
bot_reachable() { ping -c1 -W2 "$BOT_HOST" >/dev/null 2>&1; }
bot_login_ok()  { bot_ssh id >/dev/null; }

start_mcp() {
  nohup "$PROJECT_DIR/run_mcp_server.py" >> "$PROJECT_DIR/logs/run_stdout.log" 2>&1 &
  sleep 3
  mcp_listening && ok "MCP server started (pid $!)" || bad "still not listening; see logs/run_stdout.log"
}

# ---- individual checks -------------------------------------------------------------

check_mcp_server() {
  hdr "MCP server on this desktop"
  if mcp_listening; then
    ok "port $MCP_PORT is listening"
    local code
    code=$(curl -s -m5 -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$MCP_PORT/mcp" \
      -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"triage","version":"0"}}}')
    [ "$code" = 200 ] && ok "initialize returned HTTP 200" || bad "initialize returned HTTP $code"
  else
    bad "nothing listening on port $MCP_PORT (server down; it has no systemd unit, so reboots stop it)"
    confirm "Start ./run_mcp_server.py in the background?" && start_mcp
  fi
}

check_ip() {
  hdr "Desktop IP vs URL configured on $BOT_HOST"
  local mine cfg
  mine=$(hostname -I | tr ' ' '\n' | grep '^192\.168\.1\.' | head -1)
  cfg=$(bot_ssh "grep -o 'http://[0-9.]*:$MCP_PORT/mcp' ~/.openclaw/openclaw.json | head -1")
  info "desktop LAN IP: ${mine:-unknown}   configured URL: ${cfg:-unreadable}"
  if [[ -n "$mine" && "$cfg" == *"//$mine:"* ]]; then ok "they match"
  else bad "mismatch. Edit mcp.servers.hybrid-rag.url in ~/.openclaw/openclaw.json on $BOT_HOST (or reserve a static IP), then restart the gateway. Not automated."; fi
}

check_bot_up() {
  hdr "$BOT_HOST reachable / booted"
  if bot_reachable; then ok "ping works"; else
    bad "no ping. VM is down, still booting, or network is out."
    if command -v virsh >/dev/null && virsh list --all 2>/dev/null | grep -q "$BOT_VM.*shut off"; then
      warn "libvirt domain $BOT_VM is shut off"
      confirm "Start it with 'virsh start $BOT_VM'?" && virsh start "$BOT_VM" && info "wait 1-2 min for boot and gateway start"
    fi
    return 1
  fi
}

check_ssh_login() {
  hdr "SSH login to $BOT_USER@$BOT_HOST"
  [ -r "$BOT_KEY" ] && ok "key file readable: $BOT_KEY" || { bad "key file missing/unreadable: $BOT_KEY"; return 1; }
  local perm; perm=$(stat -c %a "$BOT_KEY"); [ "$perm" = 600 ] && ok "key permissions 600" || {
    bad "key permissions are $perm (ssh refuses keys that are group/world readable)"
    confirm "chmod 600 $BOT_KEY?" && chmod 600 "$BOT_KEY"; }
  local out; out=$(bot_ssh id)
  if [[ "$out" == uid=* ]]; then ok "login works ($out)"; return 0; fi
  bad "login failed: $out"
  case "$out" in
    *"Too many authentication failures"*) info "ssh offered too many keys: this script already uses IdentitiesOnly; check the same in your own command (-o IdentitiesOnly=yes -F /dev/null)." ;;
    *"Permission denied"*) info "key not in ~$BOT_USER/.ssh/authorized_keys on $BOT_HOST, or wrong user. Public key to install:"
                           info "$(cat "$BOT_KEY.pub" 2>/dev/null)"
                           info "Install it with an already-working login: ssh-copy-id -i $BOT_KEY.pub $BOT_USER@$BOT_HOST" ;;
    *"Connection refused"*) info "sshd not running on $BOT_HOST (VM still booting?)" ;;
    *"Host key verification"*|*"REMOTE HOST IDENTIFICATION"*) info "host key changed: verify the VM was rebuilt, then 'ssh-keygen -R $BOT_HOST'" ;;
    *"No route"*|*"timed out"*) info "network path to $BOT_HOST is down" ;;
  esac
  return 1
}

check_gateway() {
  hdr "OpenClaw gateway on $BOT_HOST"
  local st; st=$(bot_ssh "systemctl --user is-active openclaw-gateway")
  if [ "$st" = active ]; then ok "openclaw-gateway is active"
  else bad "openclaw-gateway state: $st"
       info "restart on the VM: systemctl --user restart openclaw-gateway (change on the remote VM, not automated)"; fi
  info "signal-cli errors today:"
  bot_ssh "grep -i 'signal' $(bot_log) | grep -i -E 'error|fail|exception' | tail -3 | cut -c1-200" | sed 's/^/           /'
}

check_mcp_from_bot() {
  hdr "OpenClaw's view of the MCP server"
  local fails last
  fails=$(bot_ssh "grep -c 'failed to start server \"hybrid-rag\"' $(bot_log)")
  last=$(bot_ssh "grep 'failed to start server \"hybrid-rag\"' $(bot_log) | tail -1 | grep -o '\"time\":\"[^\"]*\"'")
  if [ "${fails:-0}" = 0 ]; then ok "no MCP connect failures logged today"
  else warn "$fails connect failure(s) today; last: ${last:-?}"
       info "A session started during a failure has no $TOOL. After the server is up, send /new in Signal."; fi
  bot_ssh "python3 - <<'PY'
import json,os
d=json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))
t=\"$TOOL\"
print('mcp entry enabled:', d.get('mcp',{}).get('servers',{}).get('hybrid-rag',{}).get('enabled'))
print('tools.allow has tool:', t in d.get('tools',{}).get('allow',[]))
print('sandbox alsoAllow has tool:', t in d.get('tools',{}).get('sandbox',{}).get('tools',{}).get('alsoAllow',[]))
print('primary model:', d.get('agents',{}).get('defaults',{}).get('model',{}).get('primary'))
PY" | sed 's/^/         /'
  info "If either 'has tool' is False, add it to that list in openclaw.json and restart the gateway (manual)."
}

check_tool_called() {
  hdr "Is the MCP tool actually being called?"
  local n; n=$(grep -c 'POST /mcp' logs/run_stdout.log 2>/dev/null); info "POST /mcp requests in run_stdout.log: ${n:-0}"
  local q; q=$(ls -t logs/query_*.log 2>/dev/null | head -1)
  if [ -n "$q" ] && [ -s "$q" ]; then ok "latest query log has content: $q"; tail -3 "$q" | cut -c1-200 | sed 's/^/         /'
  else warn "latest query log is empty: no ask_documents call has reached the engine"; fi
  info "Gateway view (tool events, context size):"
  bot_ssh "grep -E 'tool_execution_started|context-pressure|ask_documents' $(bot_log) | tail -4 | cut -c1-220" | sed 's/^/           /'
  info "If replies come back but the tool is never called: model is ignoring it or session is bloated -> /new, check agents.defaults.model.primary, trim workspace files (see Doc/step-5-requirements.md)."
}

check_timing() {
  hdr "Slow answers / 60s MCP timeout"
  if command -v ollama >/dev/null; then info "loaded models:"; ollama ps 2>&1 | sed 's/^/           /'; fi
  command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader | sed 's/^/         GPU: /'
  local q; q=$(ls -t logs/query_*.log 2>/dev/null | head -1)
  [ -n "$q" ] && { info "recent timing lines in $q:"; grep -i -E 'ms|seconds|elapsed' "$q" | tail -5 | cut -c1-200 | sed 's/^/           /'; }
  grep -c 'Request timed out' "$(ls -t logs/query_*.log | head -1)" 2>/dev/null | sed 's/^/         timeouts in latest log: /'
  info "Fixes: keep the model warm (first call after idle loads it), lower OLLAMA_NUM_CTX, fewer chunks, smaller model. Benchmark: python scripts/benchmark_queries.py"
}

check_ollama() {
  hdr "Ollama and embedding model"
  if curl -s -m3 http://localhost:11434/api/tags >/dev/null; then ok "Ollama answering on :11434"
    curl -s -m3 http://localhost:11434/api/tags | grep -q nomic-embed-text && ok "embedding model nomic-embed-text present" || bad "nomic-embed-text not pulled (ollama pull nomic-embed-text)"
  else bad "Ollama not answering"
    confirm "'sudo systemctl restart ollama'?" && sudo systemctl restart ollama
  fi
}

check_engine() {
  hdr "Query engine end-to-end (CLI)"
  info "running: run_query.py 'test' (same engine the MCP tool uses)"
  if timeout 120 "$PY" run_query.py "What documents are indexed?" 2>&1 | tail -8 | cut -c1-200 | sed 's/^/           /'; then :; fi
  info "Empty/'unknown' answers: check Ollama (above), then rebuild the index: $PY run_index.py"
}

check_stale() {
  hdr "Stale index (new/changed documents not showing up)"
  local m=logs/maintenance.log problem=0
  if [ -f "$m" ]; then info "last maintenance runs:"; tail -4 "$m" | cut -c1-200 | sed 's/^/           /'
    # judge only the most recent completed run, not older failures still in the log
    local last_end; last_end=$(grep '=== maintenance run end:' "$m" | tail -1)
    if [ -z "$last_end" ]; then warn "no completed maintenance run found in $m"; problem=1
    elif [[ "$last_end" == *FAILED* ]]; then bad "latest maintenance run FAILED: ${last_end#* }"; problem=1
    else ok "latest maintenance run OK: ${last_end#* }"; fi
  else warn "no $m found; maintenance may never have run"; problem=1; fi
  local last_idx; last_idx=$(grep 'stage index: ok' "$m" 2>/dev/null | tail -1 | cut -d' ' -f1 | tr T ' ')
  info "last successful index: ${last_idx:-never (per $m)}"
  # unattended (--yes): don't kick off a long re-index unless there is evidence of a problem
  if [ "$ASSUME_YES" = 1 ] && [ "$problem" = 0 ]; then info "--yes: no problem detected, not re-indexing (use menu 5 interactively to force)"; return 0; fi
  confirm "Run ./run_maintenance.sh now (ingest -> chunk -> index; can take minutes, sends an email report)?" && ./run_maintenance.sh
}

check_reboot() {
  hdr "After a desktop reboot"
  pgrep -f run_mcp_server.py >/dev/null && ok "run_mcp_server.py running" || { bad "run_mcp_server.py not running"; confirm "Start it?" && start_mcp; }
  info "No systemd unit yet, so this must be done after every reboot."
}

run_all() { check_mcp_server; check_ip; if check_bot_up && check_ssh_login; then check_gateway; check_mcp_from_bot; check_tool_called; fi; check_ollama; check_stale; }

remote_chain() { check_bot_up && check_ssh_login && "$@"; }

menu() {
cat <<EOM

 Hybrid RAG triage
  1) Signal says it can't find $TOOL
  2) No reply from Signal at all ($BOT_HOST down / booting / gateway / signal-cli)
  3) Replies, but the MCP server is never called (wrong model / bloated session)
  4) Request timed out after 60s / very slow answers
  5) Stale answers: new documents missing (re-index)
  6) Empty or "I don't know" answers (retrieval / Ollama)
  7) Can't SSH into $BOT_HOST (key issue)
  8) Desktop IP changed / desktop was rebooted
  9) Run all quick checks
  q) Quit
EOM
}

dispatch() {
  case "$1" in
    1) check_mcp_server; check_ip; remote_chain check_mcp_from_bot ;;
    2) check_bot_up && check_ssh_login && check_gateway ;;
    3) check_tool_called; remote_chain check_mcp_from_bot ;;
    4) check_timing; check_ollama ;;
    5) check_stale ;;
    6) check_ollama; check_engine ;;
    7) check_bot_up && check_ssh_login ;;
    8) check_reboot; check_ip ;;
    9) run_all ;;
    *) echo "  unknown choice: $1"; FAILS=$((FAILS+1)) ;;
  esac
}

CHOICES=()
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    [1-9]) CHOICES+=("$1") ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# Non-interactive mode: explicit choices, or --yes alone => run everything once.
if [ ${#CHOICES[@]} -gt 0 ] || [ "$ASSUME_YES" = 1 ]; then
  [ ${#CHOICES[@]} -eq 0 ] && CHOICES=(9)
  for c in "${CHOICES[@]}"; do dispatch "$c"; done
  [ "$FAILS" -eq 0 ]; exit
fi

while true; do
  menu; read -r -p " choice: " c || exit 0
  case "$c" in
    q|Q) exit 0 ;;
    *) dispatch "$c" ;;
  esac
done
