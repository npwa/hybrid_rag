"""T-DOC-1 (FR-X.2, DOC1, DOC2): every warning the console can show maps to a runbook that exists; docs link to real files."""
import dataclasses
import re

from fastapi.testclient import TestClient

from console import runbooks
from console.api import create_app
from tests.conftest import ROOT

DOC_REF = re.compile(r"Doc/(?:Runbooks|Issues|Postmortems)/[\w.-]+\.md|Doc/step-[\w.-]+\.md|Doc/console-guide\.md")


def test_every_registered_warning_points_at_an_existing_runbook():
    assert len(runbooks.WARNINGS) >= 20
    for wid, (title, fname) in runbooks.WARNINGS.items():
        assert title and (ROOT / runbooks.RUNBOOK_DIR / fname).exists(), wid


def test_every_runbook_file_is_used_and_has_the_standard_sections():
    used = {f for _, f in runbooks.WARNINGS.values()}
    on_disk = {p.name for p in (ROOT / "Doc" / "Runbooks").glob("*.md")}
    assert on_disk - used == set(), f"runbooks no warning links to: {on_disk - used}"
    for f in on_disk:
        text = (ROOT / "Doc" / "Runbooks" / f).read_text()
        assert text.startswith("# Runbook:") and "**Shown as:**" in text, f
        if f != "index-failure-causes.md":          # that one is a catalogue with one section per cause (see test_docs.py)
            assert "## Check" in text, f


def test_every_flag_kind_the_agent_log_can_raise_has_a_runbook():
    src = (ROOT / "console" / "readers" / "agent_log.py").read_text()
    kinds = set(re.findall(r'"kind": "([a-z_]+)"', src))
    assert {"mcp_connect_failure", "host_gap", "looks_like_tool_call"} <= kinds
    assert not kinds - set(runbooks.WARNINGS), kinds - set(runbooks.WARNINGS)


def test_every_warning_id_used_in_code_is_registered():
    ids = set()
    for p in (ROOT / "console").glob("*.py"):
        ids |= set(re.findall(r'(?:warn|runbook_path)\(\s*"([a-z_]+)"', p.read_text()))
        ids |= set(re.findall(r'^\s+\("([a-z_]+)", f"', p.read_text(), re.M))        # the warning table in queries.py
        ids |= set(re.findall(r'"id": "([a-z_]+)"', p.read_text()))
    ids -= {"id"}
    assert ids and not ids - set(runbooks.WARNINGS), ids - set(runbooks.WARNINGS)


def test_runbook_endpoint_lists_the_registry(client):
    items = client.get("/api/v1/runbooks").json()
    assert {i["id"] for i in items} == set(runbooks.WARNINGS)
    assert all((ROOT / i["runbook"]).exists() for i in items)


def test_health_warnings_name_a_runbook_when_services_are_down(demo_config, monkeypatch):
    from console import health
    monkeypatch.setattr(health, "_tcp_listening", lambda port: False)
    monkeypatch.setattr(health, "_http_ok", lambda url: False)
    cfg = dataclasses.replace(demo_config, demo=False)
    d = TestClient(create_app(cfg), base_url="http://localhost").get("/api/v1/health").json()
    ids = {w["id"] for w in d["warnings"]}
    assert {"mcp_down", "ollama_down"} <= ids
    for w in d["warnings"]:
        assert (ROOT / w["runbook"]).exists() and w["text"]


def test_healthy_demo_has_no_warnings(client):
    assert client.get("/api/v1/health").json()["warnings"] == []


def test_toolcall_flags_carry_runbooks(client):
    flags = client.get("/api/v1/toolcalls/summary?days=30").json()["flags"]
    assert flags and all(f["runbook"] and (ROOT / f["runbook"]).exists() for f in flags)


def test_missing_agent_logs_warn_with_runbook(demo_config, tmp_path):
    cfg = dataclasses.replace(demo_config, agent_logs_dir=tmp_path / "none")
    d = TestClient(create_app(cfg), base_url="http://localhost").get("/api/v1/toolcalls/summary").json()
    assert d["available"] is False and d["warnings"][0]["id"] == "agent_logs_missing"
    assert (ROOT / d["warnings"][0]["runbook"]).exists()


def test_query_warnings_when_rates_are_high(client):
    ids = {w["id"] for w in client.get("/api/v1/queries/stats?days=30").json()["warnings"]}
    assert "query_errors" in ids and "slow_answers" in ids       # the demo month has both


def test_doc_references_in_docs_resolve():
    files = [ROOT / "README.md", ROOT / "Doc" / "console-guide.md", *(ROOT / "Doc" / "Runbooks").glob("*.md"),
             *(ROOT / "Doc" / "Postmortems").glob("*.md")]
    for f in files:
        for ref in DOC_REF.findall(f.read_text()):
            assert (ROOT / ref).exists(), f"{f.name}: {ref}"
        for ref in re.findall(r"\]\((PM-[\w.-]+\.md)\)", f.read_text()):
            assert (f.parent / ref).exists(), f"{f.name}: {ref}"
        for hyr in re.findall(r"HYR-\d\d", f.read_text()):
            assert (ROOT / "Doc" / "Issues" / f"{hyr}.md").exists(), f"{f.name}: {hyr}"


def test_postmortems_follow_the_format_and_cover_the_six_incidents():
    pm = sorted((ROOT / "Doc" / "Postmortems").glob("PM-*.md"))
    assert [p.name[:5] for p in pm] == [f"PM-0{i}" for i in range(1, 7)]
    for p in pm:
        text = p.read_text()
        for section in ("## Summary", "## Impact", "## Timeline", "## Detection", "## Root cause", "## Fix", "## Prevention"):
            assert section in text, f"{p.name}: {section}"
    index = (ROOT / "Doc" / "Postmortems" / "README.md").read_text()
    assert all(p.name in index for p in pm)


def test_triage_sections_point_at_existing_runbooks():
    refs = re.findall(r'hdr "[^"]*" ([a-z-]+\.md)', (ROOT / "scripts" / "triage.sh").read_text())
    assert len(refs) >= 8
    for r in refs:
        assert (ROOT / "Doc" / "Runbooks" / r).exists(), r
