import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def build_demo(out: Path, seed: int = 20261030) -> Path:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_synthetic_data.py"), "--out", str(out),
                    "--seed", str(seed), "--force"], check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory) -> Path:
    """The synthetic dataset, built once per test session (never touches real data)."""
    return build_demo(tmp_path_factory.mktemp("demo") / "demo_data")


@pytest.fixture()
def demo_config(demo_dir):
    from console.config import ConsoleConfig
    return ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True, working_dir=demo_dir)


@pytest.fixture()
def client(demo_config):
    from fastapi.testclient import TestClient
    from console.api import create_app
    return TestClient(create_app(demo_config), raise_server_exceptions=False)
