"""T-SEC-*: the console refuses writes, foreign Host headers (DNS rebinding) and sends hardening headers."""
import dataclasses

from fastapi.testclient import TestClient

from console.api import create_app


def test_only_the_explorer_accepts_post_and_nothing_accepts_put_patch_delete(demo_config):
    app = create_app(demo_config)
    methods = {(m, r.path) for r in app.routes if hasattr(r, "methods") for m in r.methods
               if r.path.startswith("/api/") and m not in ("GET", "HEAD")}
    assert methods == {("POST", "/api/v1/explore")}


def test_write_methods_are_refused_before_reaching_a_route(client):
    for method in ("put", "patch", "delete", "post"):
        r = getattr(client, method)("/api/v1/health")
        assert r.status_code == 405 and r.json()["error"] == "read_only"
    assert client.post("/api/v1/index/summary").status_code == 405


def test_foreign_host_header_is_refused_on_loopback(demo_config):
    c = TestClient(create_app(demo_config), base_url="http://localhost")
    for host in ("evil.example.com", "evil.example.com:8300", "192.168.1.53:8300", "localhost.evil.com"):
        r = c.get("/api/v1/health", headers={"Host": host})
        assert r.status_code == 421 and r.json()["error"] == "bad_host", host
    for host in ("localhost", "localhost:8300", "127.0.0.1:8300", "[::1]:8300"):
        assert c.get("/api/v1/health", headers={"Host": host}).status_code == 200, host


def test_host_check_is_off_when_the_operator_binds_elsewhere(demo_config):
    cfg = dataclasses.replace(demo_config, host="0.0.0.0")
    c = TestClient(create_app(cfg), base_url="http://desk.lan:8300")
    assert c.get("/api/v1/health").status_code == 200


def test_hardening_headers_on_api_and_page(client):
    r = client.get("/api/v1/health")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_cross_origin_requests_get_no_cors_permission(client):
    r = client.get("/api/v1/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers
    assert client.options("/api/v1/explore", headers={"Origin": "https://evil.example.com",
                                                     "Access-Control-Request-Method": "POST"}).status_code == 405


def test_static_path_traversal_is_not_served(client):
    secret = (open("config/console_config.example.yaml").read().splitlines()[3:4] or [""])[0].strip()
    readme_marker = "Operator console"        # appears in README.md, never in the built page or the placeholder
    for p in ("/../config/console_config.example.yaml", "/%2e%2e/config/console_config.example.yaml", "/..%2f..%2fREADME.md",
              "/../README.md", "/assets/../../README.md"):
        r = client.get(p)
        assert readme_marker not in r.text and (not secret or secret not in r.text), p
