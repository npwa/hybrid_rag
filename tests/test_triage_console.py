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


def run_triage(tmp_path, *args, health=None, http_code="200", listening=True, env_extra=None, stdin="", files_total=3):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (tmp_path / "body.json").write_text(json.dumps(health if health is not None else HEALTHY))
    (tmp_path / "summary.json").write_text(json.dumps({"files_total": files_total}))
    fake_ss = "#!/bin/sh\n" + ('echo "LISTEN 0 128 127.0.0.1:8399 0.0.0.0:*"\n' if listening else "exit 0\n")
    fake_curl = (f'#!/bin/sh\ncase "$*" in *index/summary*) cat {tmp_path}/summary.json; exit 0;; esac\n'
                 f'cat {tmp_path}/body.json\nprintf "\\n{http_code}"\n')
    for name, text in (("ss", fake_ss), ("curl", fake_curl)):
        f = bindir / name
        f.write_text(text)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CONSOLE_PORT": "8399", "NO_COLOR": "1",
           "AGENT_DIR": str(tmp_path / "agent"), **(env_extra or {})}
    return subprocess.run([str(TRIAGE), *args], capture_output=True, text=True, env=env, input=stdin, timeout=90, cwd=ROOT)


def make_manifest(tmp_path, n=3):
    import sqlite3
    db = tmp_path / "manifest.db"
    db.unlink(missing_ok=True)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE files (file_id TEXT)")
    c.executemany("INSERT INTO files VALUES (?)", [(str(i),) for i in range(n)])
    c.commit(); c.close()
    return db


def healthy_with_manifest(tmp_path, n=3):
    h = json.loads(json.dumps(HEALTHY))
    h["sources"][0]["path"] = str(make_manifest(tmp_path, n))
    return h


def test_index_summary_matches_manifest(tmp_path):                              # C5 ok
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path, 3), files_total=3)
    assert "[ OK ] index summary matches the manifest (3 files)" in r.stdout and r.returncode == 0


def test_index_summary_mismatch_is_a_failure(tmp_path):                         # C5 fail
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path, 5), files_total=3)
    assert "[FAIL] index summary says 3 files but the manifest has 5" in r.stdout and r.returncode == 1


def test_healthy_console_all_ok(tmp_path):                                      # T-TRI-2 (healthy)
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path))
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


def make_agent_copy(tmp_path, age_hours):
    d = tmp_path / "agent"
    d.mkdir(exist_ok=True)
    f = d / "openclaw-2026-10-30.abcd1234.log"
    f.write_text("{}\n")
    t = __import__("time").time() - age_hours * 3600
    os.utime(f, (t, t))


def test_c6_no_copies_warns_and_yes_runs_the_pull(tmp_path):                      # C6
    flag = tmp_path / "pulled.flag"
    r = run_triage(tmp_path, "-y", "10", health=healthy_with_manifest(tmp_path), env_extra={"PULL_CMD": f"touch {flag}"})
    assert "no OpenClaw logs copied yet" in r.stdout and flag.exists() and r.returncode == 0


def test_c6_fresh_copy_is_ok_stale_copy_warns(tmp_path):
    make_agent_copy(tmp_path, 2)
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path))
    assert "OpenClaw log copies are fresh (newest 2 h old)" in r.stdout
    make_agent_copy(tmp_path, 50)
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path), stdin="n\n")
    assert "newest OpenClaw log copy is 50 h old (limit 36 h)" in r.stdout and r.returncode == 0   # a warning, not a failure
    flag = tmp_path / "pulled.flag"
    r = run_triage(tmp_path, "-y", "10", health=healthy_with_manifest(tmp_path), env_extra={"PULL_CMD": f"touch {flag}"})
    assert flag.exists()


def fake_systemctl(tmp_path, installed=True, active="active", enabled="enabled"):
    f = tmp_path / "systemctl"
    log = tmp_path / "systemctl.calls"
    f.write_text("#!/bin/sh\n" f'echo "$*" >> {log}\n'
                 + ('case "$2" in cat) exit 1;; esac\n' if not installed else "")
                 + f'case "$2" in is-active) echo {active};; is-enabled) echo {enabled};; esac\nexit 0\n')
    f.chmod(0o755)
    return f, log


def test_c10_reports_active_enabled_unit(tmp_path):                               # C10
    sc, _ = fake_systemctl(tmp_path)
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path), env_extra={"SYSTEMCTL": str(sc)})
    assert "systemd unit hybrid-rag-console: active (enabled)" in r.stdout and r.returncode == 0


def test_c10_missing_unit_points_to_installer(tmp_path):
    sc, _ = fake_systemctl(tmp_path, installed=False)
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path), env_extra={"SYSTEMCTL": str(sc)})
    assert "no systemd unit hybrid-rag-console (install with scripts/install_services.sh" in r.stdout


def test_c10_inactive_or_disabled_unit_warns(tmp_path):
    sc, _ = fake_systemctl(tmp_path, active="failed", enabled="disabled")
    r = run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path), env_extra={"SYSTEMCTL": str(sc)})
    assert "systemd unit hybrid-rag-console is failed (disabled)" in r.stdout and "systemctl --user enable hybrid-rag-console" in r.stdout


def test_console_down_with_unit_starts_it_through_systemd(tmp_path):
    sc, log = fake_systemctl(tmp_path, active="inactive")
    run_triage(tmp_path, "-y", "10", listening=False, env_extra={"SYSTEMCTL": str(sc)})
    assert "--user restart hybrid-rag-console" in log.read_text()


def test_mcp_down_with_unit_starts_it_through_systemd(tmp_path):
    sc, log = fake_systemctl(tmp_path, active="inactive")
    run_triage(tmp_path, "-y", "1", listening=False, env_extra={"SYSTEMCTL": str(sc), "MCP_PORT": "8398", "BOT_HOST": "127.0.0.1"})
    assert "--user restart hybrid-rag-mcp" in log.read_text()


def test_prompts_say_restart_service_when_the_unit_is_installed(tmp_path):
    sc, _ = fake_systemctl(tmp_path, active="inactive")
    r = run_triage(tmp_path, "-y", "1", listening=False, env_extra={"SYSTEMCTL": str(sc), "MCP_PORT": "8398", "BOT_HOST": "127.0.0.1"})
    assert "Restart the hybrid-rag-mcp service (systemctl --user restart)? apply the fix?" in r.stdout
    r = run_triage(tmp_path, "-y", "10", listening=False, env_extra={"SYSTEMCTL": str(sc)})
    assert "Restart the hybrid-rag-console service" in r.stdout
    sc, _ = fake_systemctl(tmp_path, installed=False)
    r = run_triage(tmp_path, "-y", "10", listening=False, env_extra={"SYSTEMCTL": str(sc), "CONSOLE_START_CMD": "true"})
    assert "Start ./run_console.py in the background?" in r.stdout


def test_ok_lines_from_the_python_blocks_are_coloured_on_a_terminal(tmp_path):
    import pty
    run_triage(tmp_path, "10", health=healthy_with_manifest(tmp_path))   # builds bin/ and body files
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "CONSOLE_PORT": "8399", "AGENT_DIR": str(tmp_path / "agent")}
    env.pop("NO_COLOR", None)
    master, slave = pty.openpty()
    p = subprocess.Popen([str(TRIAGE), "10"], stdout=slave, stderr=slave, env=env, cwd=ROOT)
    os.close(slave)
    out = b""
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    p.wait()
    text = out.decode()
    for needle in ("API healthy", "read-only access to data", "data sources:", "index summary matches"):
        line = next(l for l in text.splitlines() if needle in l)
        assert "\x1b[32m" in line, line
