from pathlib import Path

import console
from console.config import ConsoleConfig

ROOT = Path(__file__).resolve().parent.parent


def test_package_version():
    assert console.__version__


def test_example_config_loads_and_resolves_paths():
    cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml")
    assert cfg.port == 8300 and cfg.host == "127.0.0.1"          # loopback by default (C4)
    assert cfg.manifest_db.name == "manifest.db" and cfg.manifest_db.is_absolute()
    assert cfg.agent_logs_dir == cfg.logs_dir / "agent"
    assert not cfg.demo


def test_demo_mode_points_at_demo_dir_and_unmasks():
    cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True)
    assert cfg.working_dir.name == "demo_data" and cfg.demo
    assert str(cfg.manifest_db).startswith(str(cfg.working_dir))
