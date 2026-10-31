"""T-API-*: shapes, errors, health content, static serving, security defaults."""
import sqlite3

from fastapi.testclient import TestClient

from console.api import create_app
from console.config import ConsoleConfig
from tests.conftest import ROOT
import run_console


def test_health_shape_and_read_only_flags(client):                             # T-API-6, C3, C4
    h = client.get("/api/v1/health").json()
    assert h["status"] == "ok" and h["demo"] is True and h["version"]
    src = {s["name"]: s for s in h["sources"]}
    assert src["manifest"]["present"] and src["manifest"]["read_only"] is True
    assert src["lancedb"]["present"] and src["lancedb"]["read_only"] is True
    assert src["maintenance_log"]["present"] and src["agent_logs"]["present"]
    assert h["services"]["mcp_server"]["state"].startswith("n/a")              # no probes in demo mode
    m = h["maintenance"]
    assert m["last_run"]["result"] == "OK" and m["last_successful_index"]
    assert m["stale"] in (True, False) and m["stale_after_hours"] == 36
    assert h["index"]["chunks"] > 0 and h["index"]["ann_threshold_chunks"] == 200_000


def test_stale_flag_follows_threshold(demo_config):
    demo_config.stale_after_hours = 10_000
    h = TestClient(create_app(demo_config)).get("/api/v1/health").json()
    assert h["maintenance"]["stale"] is False
    demo_config.stale_after_hours = 0.001
    h = TestClient(create_app(demo_config)).get("/api/v1/health").json()
    assert h["maintenance"]["stale"] is True


def test_index_summary_counts_equal_independent_sql(client, demo_dir):          # basis for T-P1-1
    s = client.get("/api/v1/index/summary").json()
    c = sqlite3.connect(f"file:{demo_dir / 'manifest.db'}?mode=ro", uri=True)
    assert s["files_total"] == c.execute("SELECT count(*) FROM files").fetchone()[0]
    assert s["files_by_status"] == dict(c.execute("SELECT status, count(*) FROM files GROUP BY 1"))
    assert s["chunks_total"] == c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert s["chunks_by_embedding_status"] == {"embedded": s["chunks_total"]}
    assert sum(e["count"] for e in s["files_by_extension"]) <= s["files_total"]


def test_missing_manifest_gives_json_error_not_a_stack_trace(demo_config, tmp_path):   # API4
    demo_config.manifest_db = tmp_path / "nope.db"
    c = TestClient(create_app(demo_config), raise_server_exceptions=False)
    r = c.get("/api/v1/index/summary")
    assert r.status_code == 503 and r.json()["error"] == "source_unavailable"
    h = c.get("/api/v1/health").json()                                          # health itself never fails
    assert h["status"] == "degraded" and not {s["name"]: s for s in h["sources"]}["manifest"]["present"]


def test_corrupt_manifest_degrades_cleanly(demo_config, tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database" * 100)
    demo_config.manifest_db = bad
    c = TestClient(create_app(demo_config), raise_server_exceptions=False)
    assert c.get("/api/v1/health").status_code == 200
    r = c.get("/api/v1/index/summary")
    assert r.status_code == 500 and r.json()["error"] == "internal_error" and "Traceback" not in r.text


def test_unknown_api_path_is_json_404_and_root_is_html(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    root = client.get("/")
    assert root.status_code == 200 and "Hybrid RAG console" in root.text


def test_openapi_schema_documents_endpoints(client):                            # API1
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/health" in paths and "/api/v1/index/summary" in paths


def test_built_ui_is_served_when_present(demo_config, tmp_path):
    (tmp_path / "index.html").write_text("<h1>built ui</h1>")
    demo_config.static_dir = tmp_path
    c = TestClient(create_app(demo_config))
    assert "built ui" in c.get("/").text and c.get("/api/v1/health").status_code == 200


def test_default_bind_is_loopback_and_lan_bind_warns():                         # T-SEC-1
    cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml")
    assert cfg.host == "127.0.0.1" and run_console.bind_warning(cfg.host) is None
    assert "no authentication" in run_console.bind_warning("0.0.0.0")
    assert run_console.bind_warning("192.168.1.53")


def test_no_write_methods_exposed(client):
    for path in ("/api/v1/health", "/api/v1/index/summary"):
        for method in ("post", "put", "delete", "patch"):
            assert getattr(client, method)(path).status_code == 405
