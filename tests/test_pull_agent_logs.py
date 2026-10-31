"""T-PULL-1: scripts/pull_agent_logs.sh with a fake `ssh` that runs the remote command against a local directory."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PULL = ROOT / "scripts" / "pull_agent_logs.sh"

FAKE_SSH = r'''#!/bin/bash
# fake ssh: the remote command is the LAST argument; REMOTE_DIR is a local directory here
cmd="${@: -1}"
[ -f "$FAKE_FAIL" ] && { echo "$(cat "$FAKE_FAIL")" >&2; exit 255; }
case "$cmd" in
  logs) ls -1 "$REMOTE_DIR" | grep -E '^openclaw-(dev-)?[0-9-]+\.log$' ;;
  "log "*) cat "$REMOTE_DIR/openclaw-${cmd#log }.log" ;;
  config) cat "$REMOTE_DIR/config-summary.json" ;;
  *) bash -c "$cmd" ;;
esac
'''


def line(i, tag="a"):
    return f'{{"0":"{{\\"subsystem\\":\\"gateway\\"}}","1":"{tag} line {i}","time":"2026-10-30T09:00:{i:02d}.000-07:00"}}\n'


@pytest.fixture()
def env(tmp_path):
    remote, dest, bindir = tmp_path / "remote", tmp_path / "dest", tmp_path / "bin"
    for d in (remote, bindir):
        d.mkdir()
    ssh = bindir / "ssh"
    ssh.write_text(FAKE_SSH)
    ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)
    e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "REMOTE_DIR": str(remote), "DEST": str(dest),
         "BOT_KEY": str(tmp_path / "nokey"), "FAKE_FAIL": str(tmp_path / "fail")}
    return remote, dest, e, tmp_path


def pull(e, *args):
    return subprocess.run([str(PULL), *args], capture_output=True, text=True, env=e, timeout=60)


def local_logs(dest):
    return sorted(p.name for p in dest.glob("openclaw-*.log"))


def test_first_pull_copies_new_files_second_pull_copies_nothing(env):               # T-PULL-1 (idempotent)
    remote, dest, e, _ = env
    (remote / "openclaw-2026-10-29.log").write_text(line(1) + line(2))
    (remote / "openclaw-2026-10-30.log").write_text(line(3))
    (remote / "openclaw-dev-2026-10-30.log").write_text(line(9, "dev"))          # dev instance: never copied
    (remote / "config-summary.json").write_text('{"primary_model": "m"}')
    r = pull(e)
    assert r.returncode == 0, r.stderr
    names = local_logs(dest)
    assert len(names) == 2 and all(n.startswith("openclaw-2026-10-") and ".dev" not in n and "dev-" not in n for n in names)
    assert "2 new" in r.stdout and (dest / "config-summary.json").read_text().strip() == '{"primary_model": "m"}'
    before = {n: (dest / n).read_bytes() for n in names}
    r2 = pull(e)
    assert r2.returncode == 0 and "0 new, 0 grown, 2 unchanged" in r2.stdout
    assert {n: (dest / n).read_bytes() for n in names} == before


def test_growing_file_is_appended_not_rewritten(env):
    remote, dest, e, _ = env
    f = remote / "openclaw-2026-10-30.log"
    f.write_text(line(1) + line(2))
    pull(e)
    (name,) = local_logs(dest)
    inode = (dest / name).stat().st_ino
    f.write_text(line(1) + line(2) + line(3))
    r = pull(e)
    assert "1 grown" in r.stdout and (dest / name).read_text() == f.read_text()
    assert (dest / name).stat().st_ino == inode                                   # appended in place


def test_vm_reboot_restarts_the_same_filename_and_both_incarnations_are_kept(env):       # day-boundary / reboot
    remote, dest, e, _ = env
    f = remote / "openclaw-2026-10-30.log"
    f.write_text(line(1, "before reboot") + line(2, "before reboot"))
    pull(e)
    f.write_text(line(5, "after reboot"))                                       # /tmp cleared; OpenClaw starts the day again
    r = pull(e)
    assert r.returncode == 0 and "1 new" in r.stdout
    names = local_logs(dest)
    assert len(names) == 2
    texts = [(dest / n).read_text() for n in names]
    assert any("before reboot" in t for t in texts) and any("after reboot" in t for t in texts)
    f.write_text(line(5, "after reboot") + line(6, "after reboot"))
    assert "1 grown" in pull(e).stdout and len(local_logs(dest)) == 2


def test_shorter_remote_prefix_keeps_local_copy(env):
    remote, dest, e, _ = env
    f = remote / "openclaw-2026-10-30.log"
    f.write_text(line(1) + line(2))
    pull(e)
    f.write_text(line(1))                                                       # same incarnation, shorter (e.g. truncated): keep ours
    r = pull(e)
    (name,) = local_logs(dest)
    assert r.returncode == 0 and (dest / name).read_text() == line(1) + line(2)


def test_unreadable_vm_is_a_clear_error_not_an_empty_file(env):                    # HYR-10 condition
    remote, dest, e, tmp = env
    (remote / "openclaw-2026-10-30.log").write_text(line(1))
    (tmp / "fail").write_text("ls: cannot open directory '/tmp/openclaw': Permission denied")
    r = pull(e)
    assert r.returncode == 1 and "permission denied" in r.stderr.lower() and "HYR-10" in r.stderr
    assert local_logs(dest) == []
    (tmp / "fail").write_text("ssh: connect to host npabot-u24 port 22: No route to host")
    r = pull(e)
    assert r.returncode == 1 and "No route to host" in r.stderr and local_logs(dest) == []


def test_dry_run_writes_nothing(env):
    remote, dest, e, _ = env
    (remote / "openclaw-2026-10-30.log").write_text(line(1))
    (remote / "config-summary.json").write_text('{"a": 1}')
    r = pull(e, "--dry-run")
    assert r.returncode == 0 and "new" in r.stdout and "dry run" in r.stdout
    assert local_logs(dest) == [] and not (dest / "config-summary.json").exists()


def test_quiet_prints_nothing_on_success_and_wrapper_mode_works(env):
    remote, dest, e, _ = env
    (remote / "openclaw-2026-10-30.log").write_text(line(1))
    (remote / "config-summary.json").write_text('{"a": 1}')
    r = pull(e, "-q")
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    e2 = {**e, "BOT_WRAPPER": "1", "DEST": str(dest.parent / "dest2")}
    r = pull(e2)
    assert r.returncode == 0 and len(list((dest.parent / "dest2").glob("openclaw-*.log"))) == 1


def test_help_and_bad_argument():
    r = subprocess.run([str(PULL), "--help"], capture_output=True, text=True, cwd="/")
    assert r.returncode == 0 and "Usage:" in r.stdout and "reboot" in r.stdout
    assert subprocess.run([str(PULL), "--bogus"], capture_output=True, text=True).returncode == 2
