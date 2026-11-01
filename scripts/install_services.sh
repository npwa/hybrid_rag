#!/usr/bin/env bash
# Install the systemd --user units for the MCP server (HYR-01) and the operator console.
#
# Usage:  scripts/install_services.sh [--enable] [--dest DIR] [--uninstall]
#   (no flags)   render deploy/systemd/*.service into ~/.config/systemd/user and run daemon-reload.
#                Nothing is enabled or started.
#   --enable     also `systemctl --user enable --now` both units (stop any hand-started
#                run_mcp_server.py / run_console.py first: they hold ports 8200 / 8300).
#   --dest DIR   render into DIR instead (no systemctl calls; used by the tests).
#   --uninstall  disable and remove both units.
# Survive reboots without a login session:  loginctl enable-linger "$USER"   (printed, never run here)
set -eu
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNITS=(hybrid-rag-mcp hybrid-rag-console)
DEST="$HOME/.config/systemd/user"; CUSTOM=0; ENABLE=0; UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --enable) ENABLE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --dest) DEST="$2"; CUSTOM=1; shift ;;
    -h|--help) sed -n '2,/^set /p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
sc() { [ "$CUSTOM" = 1 ] || systemctl --user "$@"; }

if [ "$UNINSTALL" = 1 ]; then
  for u in "${UNITS[@]}"; do sc disable --now "$u.service" 2>/dev/null || true; rm -f "$DEST/$u.service"; echo "removed $u"; done
  sc daemon-reload; exit 0
fi
[ -x "$PROJECT_DIR/.venv/bin/python" ] || { echo "no $PROJECT_DIR/.venv/bin/python: create the virtualenv first (README)" >&2; exit 1; }
mkdir -p "$DEST" "$PROJECT_DIR/logs"
for u in "${UNITS[@]}"; do
  sed "s#@PROJECT_DIR@#$PROJECT_DIR#g" "$PROJECT_DIR/deploy/systemd/$u.service" > "$DEST/$u.service"
  echo "installed $DEST/$u.service"
done
sc daemon-reload
if [ "$ENABLE" = 1 ]; then for u in "${UNITS[@]}"; do sc enable --now "$u.service"; done; fi
[ "$CUSTOM" = 1 ] || { loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes || echo "note: lingering is off, so the units stop at logout and do not start at boot until you run: loginctl enable-linger $USER"; }
