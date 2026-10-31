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


@pytest.fixture(scope="session")
def live_console(demo_dir):
    """The real FastAPI app + the built web UI on a free local port, for browser tests."""
    import socket
    import threading
    import time

    import uvicorn

    from console.api import create_app
    from console.config import ConsoleConfig

    dist = ROOT / "console" / "web" / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("web UI not built (cd console/web && npm install && npm run build)")
    cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True, working_dir=demo_dir)
    cfg.static_dir = dist
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
