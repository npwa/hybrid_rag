#!/usr/bin/env bash
# One-shot quality gate: syntax of Python and shell, TypeScript type-check, systemd unit lint, then the tests.
# Usage: scripts/check.sh [--lint-only]     Exit status 0 only if everything passed.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
FAIL=0
step() { printf '== %s\n' "$1"; shift; if "$@"; then echo "   ok"; else echo "   FAILED"; FAIL=1; fi; }

step "python compiles" "$PY" -m compileall -q console query ingest indexing chunking scripts run_console.py run_mcp_server.py
step "shell scripts parse" bash -c 'for f in scripts/*.sh run_maintenance.sh; do bash -n "$f" || exit 1; done'
step "typescript type-check" bash -c 'cd console/web && npx --no-install tsc --noEmit'
if command -v systemd-analyze >/dev/null; then
  step "systemd units" bash -c 'd=$(mktemp -d) && scripts/install_services.sh --dest "$d" >/dev/null && systemd-analyze --user verify "$d"/*.service'
fi
step "openapi snapshot is current" "$PY" -c "
import json,sys
from console.api import create_app
from console.config import ConsoleConfig
c=ConsoleConfig.load('config/console_config.example.yaml',demo=True)
cur=create_app(c).openapi(); old=json.load(open('Doc/api/openapi.json'))
sys.exit(0 if cur==old else 1)"
[ "${1:-}" = "--lint-only" ] || step "tests" "$PY" -m pytest -q
[ "$FAIL" = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
