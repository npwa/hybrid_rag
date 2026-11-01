"""HYR-01 / M7: the systemd --user units render correctly and install without touching the real systemd."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "scripts" / "install_services.sh"


def render(tmp_path):
    subprocess.run([str(INSTALL), "--dest", str(tmp_path)], check=True, capture_output=True, text=True)
    return {p.stem: p.read_text() for p in tmp_path.glob("*.service")}


def test_units_are_rendered_with_absolute_paths_and_restart_policy(tmp_path):
    units = render(tmp_path)
    assert set(units) == {"hybrid-rag-console", "hybrid-rag-mcp"}
    for name, text in units.items():
        assert "@PROJECT_DIR@" not in text
        assert f"WorkingDirectory={ROOT}" in text and f"ExecStart={ROOT}/.venv/bin/python {ROOT}/run_" in text
        assert "Restart=on-failure" in text and "WantedBy=default.target" in text
    assert "run_mcp_server.py" in units["hybrid-rag-mcp"] and "run_console.py" in units["hybrid-rag-console"]


def test_console_unit_is_sandboxed_read_only_and_never_binds_beyond_loopback(tmp_path):
    text = render(tmp_path)["hybrid-rag-console"]
    assert "ProtectSystem=strict" in text and f"ReadWritePaths={ROOT}/logs" in text and "--host" not in text


def test_install_with_dest_does_not_call_systemctl(tmp_path):
    fake = tmp_path / "bin"; fake.mkdir()
    (fake / "systemctl").write_text("#!/bin/sh\ntouch %s/called\n" % tmp_path); (fake / "systemctl").chmod(0o755)
    import os
    subprocess.run([str(INSTALL), "--enable", "--dest", str(tmp_path / "u")], check=True, capture_output=True,
                   env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert not (tmp_path / "called").exists()


def test_uninstall_removes_the_units(tmp_path):
    render(tmp_path)
    subprocess.run([str(INSTALL), "--uninstall", "--dest", str(tmp_path)], check=True, capture_output=True)
    assert not list(tmp_path.glob("*.service"))


def test_unknown_argument_is_a_usage_error():
    assert subprocess.run([str(INSTALL), "--bogus"], capture_output=True).returncode == 2


def test_unit_verifies_with_systemd_analyze(tmp_path):
    import shutil, pytest
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze not available")
    render(tmp_path)
    r = subprocess.run(["systemd-analyze", "--user", "verify", *map(str, tmp_path.glob("*.service"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
