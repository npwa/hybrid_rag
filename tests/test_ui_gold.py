"""UI tests for the gold-question view on the Query explorer and runbook links (FR-X.2), against the demo dataset."""
import json
import subprocess
import sys

import pytest
import yaml

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

from tests.conftest import ROOT  # noqa: E402

with sync_playwright() as _p:
    _chromium_ok = __import__("os").path.exists(_p.chromium.executable_path)
pytestmark = pytest.mark.skipif(not _chromium_ok, reason="run: python -m playwright install chromium")


@pytest.fixture()
def gold_saved(demo_dir, tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "console_config.example.yaml").read_text())
    raw["demo_dir"] = str(demo_dir)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(raw))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_gold_set.py"), "--demo", "--config", str(cfg), "--save-report"],
                   check=True, capture_output=True, cwd=ROOT)
    yield
    (demo_dir / "logs" / "gold_report.json").unlink(missing_ok=True)


def test_explorer_without_a_saved_run_says_how_to_make_one(page: Page, live_console):
    page.goto(live_console + "/#/explorer")
    expect(page.get_by_role("heading", name="Gold set")).to_be_visible()
    expect(page.get_by_text("run_gold_set.py")).to_be_visible()


def test_gold_table_and_compare_banner(page: Page, live_console, gold_saved):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(live_console + "/#/explorer")
    table = page.get_by_role("table", name="Gold set results")
    expect(table.locator("tbody tr")).to_have_count(8)
    expect(page.get_by_text("8 of 8 passed")).to_be_visible()
    table.get_by_role("row", name="demo-01").get_by_role("button", name="Explore").click()
    banner = page.get_by_role("status").filter(has_text="Gold question demo-01")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("pass")
    assert errors == []


def test_tool_call_flags_name_their_runbook(page: Page, live_console):
    page.goto(live_console + "/#/tools")
    flags = page.locator("ul.flags")
    expect(flags).to_contain_text("Doc/Runbooks/mcp-server-down.md")
    expect(flags).to_contain_text("Doc/Runbooks/tool-never-called.md")
