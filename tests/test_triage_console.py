"""T-TRI-*: scripts/triage.sh console checks, driven with fake `ss` and `curl` on PATH.
Nothing real is contacted and no real console is started."""
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIAGE = ROOT / "scripts" / "triage.sh"

HEALTHY = {
    "status": "ok", "version": "0.1.0", "demo": False,
    "sources": [
        {"name": "manifest", "path": "/x/manifest.db", "present": True, "read_only": True},
        {"name": "lancedb", "path": "/x/lancedb", "present": True, "read_only": True},
        {"name": "maintenance_log", "path": "/x/m.log", "present": True, "read_only": True},
        {"name": "agent_logs", "path": "/x/agent", "present": True, "read_only": True},
        {"name": "query_jsonl_today", "path": "/x/q.jsonl", "present": True, "read_only": True},
    ],
    "maintenance": {"stale": False, "last_successful_index": "2026-10-30T20:03:06", "stale_after_hours": 36},
}


def run_triage(tmp_path, *args, health=None, http_code="200", listening=True, env_extra=None, stdin=""):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (tmp_path / "body.json").write_text(json.dumps(health if health is not None else HEALTHY))
    fake_ss = "#!/bin/sh\n" + ('echo "LISTEN 0 128 127.0.0.1:8399 0.0.0.0:*"\n' if listening else "exit 0\n")
    fake_curl = f'#!/bin/sh\ncat {tmp_path}/body.json\nprintf "\\n{http_code}"\n'
    for name, text in (("ss", fake_ss), ("curl", fake_curl)):
        f = bindir / name
        f.write_text(text)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CONSOLE_PORT": "8399", "NO_COLOR": "1", **(env_extra or {})}
    return subprocess.run([str(TRIAGE), *args], capture_output=True, text=True, env=env, input=stdin, timeout=90, cwd=ROOT)


def test_healthy_console_all_ok(tmp_path):                                      # T-TRI-2 (healthy)
    r = run_triage(tmp_path, "10")
    assert r.returncode == 0, r.stdout
    assert "[ OK ] console is listening on :8399" in r.stdout
    assert "API healthy: status=ok version=0.1.0" in r.stdout
    assert "manifest and LanceDB verified read-only" in r.stdout and "[FAIL]" not in r.stdout


def test_console_down_fails_and_offers_start_without_starting_on_no(tmp_path):    # T-TRI-1 (answer n)
    flag = tmp_path / "started.flag"
    r = run_triage(tmp_path, "10", listening=False, stdin="n\n", env_extra={"CONSOLE_START_CMD": f"touch {flag}"})
    assert r.returncode == 1
    assert "[FAIL] nothing listening on port 8399" in r.stdout
    assert not flag.exists()            # (bash `read -p` prints no prompt when stdin is a pipe)


def test_console_down_with_yes_runs_start_command(tmp_path):                      # T-TRI-1 (-y)
    flag = tmp_path / "started.flag"
    r = run_triage(tmp_path, "-y", "10", listening=False, env_extra={"CONSOLE_START_CMD": f"touch {flag}"})
    assert "apply the fix? (y/N) y  [--yes]" in r.stdout
    import time
    for _ in range(20):
        if flag.exists():
            break
        time.sleep(0.1)
    assert flag.exists()
    assert "console did not start" in r.stdout and r.returncode == 1   # the fake `ss` still reports it down


def test_run_all_treats_stopped_console_as_optional_and_never_starts_it(tmp_path):
    flag = tmp_path / "started.flag"
    r = run_triage(tmp_path, "-y", "9", listening=False, env_extra={"CONSOLE_START_CMD": f"touch {flag}"})
    assert "console not running (optional)" in r.stdout
    assert not flag.exists()


def test_api_error_is_reported_with_body(tmp_path):                              # T-TRI-2 (500)
    r = run_triage(tmp_path, "10", health={"error": "internal_error", "detail": "OperationalError"}, http_code="500")
    assert r.returncode == 1
    assert "returned HTTP 500" in r.stdout and "internal_error" in r.stdout


def test_not_read_only_is_a_hard_failure_without_fix_offer(tmp_path):            # T-TRI-3
    h = json.loads(json.dumps(HEALTHY))
    h["sources"][0]["read_only"] = False
    r = run_triage(tmp_path, "10", health=h)
    assert r.returncode == 1
    assert "[FAIL] read-only access to data: NOT guaranteed for manifest" in r.stdout
    assert "apply the fix" not in r.stdout


def test_missing_source_and_stale_index_reported(tmp_path):
    h = json.loads(json.dumps(HEALTHY))
    h["sources"][2]["present"] = False
    h["maintenance"]["stale"] = True
    r = run_triage(tmp_path, "10", health=h)
    assert "[FAIL] data sources: missing maintenance_log (/x/m.log)" in r.stdout
    assert "index looks stale" in r.stdout


def test_menu_lists_console_item():
    env = {**os.environ, "NO_COLOR": "1"}
    r = subprocess.run([str(TRIAGE)], capture_output=True, text=True, env=env, input="q\n", cwd=ROOT, timeout=30)
    assert "10) Operator console" in r.stdout


def test_help_works_from_any_directory_and_lists_choices(tmp_path):
    for flag in ("-h", "--help"):
        for cwd in (ROOT, ROOT / "scripts", tmp_path):
            r = subprocess.run([str(TRIAGE), flag], capture_output=True, text=True, cwd=cwd, timeout=30,
                               env={**os.environ, "NO_COLOR": "1"})
            assert r.returncode == 0 and r.stderr == ""
            assert "Usage:  scripts/triage.sh" in r.stdout and "-y, --yes" in r.stdout
            assert "Menu choices" in r.stdout and "10) Operator console" in r.stdout and "1) Signal says" in r.stdout
