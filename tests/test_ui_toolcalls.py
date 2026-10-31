"""UI smoke tests for Page 4, the tool-call monitor (FR-4.x), in a real browser against the demo dataset."""
import json
import re
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

with sync_playwright() as _p:
    _chromium_ok = __import__("os").path.exists(_p.chromium.executable_path)
pytestmark = pytest.mark.skipif(not _chromium_ok, reason="run: python -m playwright install chromium")


@pytest.fixture()
def tools(page: Page, live_console):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(live_console + "/#/tools")
    page.errors = errors
    return page


def api(live_console):
    return json.load(urllib.request.urlopen(live_console + "/api/v1/toolcalls/summary?days=30"))


def test_page_renders_numbers_equal_the_api(tools: Page, live_console):
    d = api(live_console)
    t = d["totals"]
    expect(tools.get_by_role("heading", name="Tool-call monitor", exact=True)).to_be_visible()
    stat = lambda label: tools.locator(".stat", has_text=label)
    expect(stat("Agent turns").locator(".stat-value")).to_have_text(str(t["turns"]))
    expect(stat("Seen by the desktop").locator(".stat-value")).to_have_text(f"{t['matched']} / {t['tool_starts']}")
    expect(stat("Tool call written as text").locator(".stat-value")).to_have_text(str(t["looks_like_tool_call"]))
    expect(stat("Seen by the desktop")).to_contain_text("started but never arrived")
    assert tools.errors == []


def test_model_table_shows_both_models_with_rates(tools: Page):
    table = tools.get_by_role("table", name="Tool calls by model")
    small = table.get_by_role("row", name=re.compile("qwen2.5:14b-instruct"))
    big = table.get_by_role("row", name=re.compile("qwen3.6:35b-a3b"))
    expect(small).to_be_visible()
    expect(big).to_contain_text("100.0%")
    expect(small).not_to_contain_text("100.0%")


def test_flags_list_names_the_outage_and_the_text_calls(tools: Page):
    flags = tools.locator("section", has=tools.get_by_role("heading", name="Needs a look"))
    expect(flags).to_contain_text("MCP connect failure")
    expect(flags).to_contain_text("Tool started, desktop saw nothing")
    expect(flags).to_contain_text("Tool call written as text")
    expect(flags).to_contain_text("Doc/Runbooks/mcp-server-down.md")


def test_by_day_table_highlights_the_outage_day(tools: Page):
    rows = tools.get_by_role("table", name="Tool calls by day").locator("tbody tr")
    expect(rows).to_have_count(14)
    expect(tools.locator("tr.row-bad")).to_have_count(1)
    expect(tools.locator("tr.row-bad")).to_contain_text("2026-10-27")


def test_chart_is_an_accessible_image_with_legend(tools: Page):
    chart = tools.get_by_role("img", name=re.compile("Time to tool for \\d+ turns"))
    expect(chart).to_be_visible()
    expect(tools.locator("figure.chart circle").first).to_be_visible()
    expect(tools.locator("figcaption")).to_contain_text("qwen2.5:14b-instruct")


def test_period_selector_changes_the_data(tools: Page):
    tools.get_by_label("Period").select_option("7")
    expect(tools.get_by_role("table", name="Tool calls by day").locator("tbody tr")).to_have_count(7)


def test_unavailable_state_explains_how_to_get_data(tools: Page):
    tools.route("**/api/v1/toolcalls/summary*", lambda r: r.fulfill(json={
        "available": False, "detail": "No OpenClaw logs found. Run scripts/pull_agent_logs.sh to copy them from the bot VM.",
        "sources": {"files": 0, "newest_file": None, "age_hours": None, "agent_logs_dir": "x", "config_summary": None, "pull_script": "scripts/pull_agent_logs.sh"}}))
    tools.reload()
    expect(tools.get_by_role("alert")).to_contain_text("pull_agent_logs.sh")


def test_stale_copy_warning_and_api_error(tools: Page, live_console):
    body = api(live_console)
    body["sources"]["age_hours"] = 70
    tools.route("**/api/v1/toolcalls/summary*", lambda r: r.fulfill(json=body))
    tools.reload()
    expect(tools.get_by_role("alert")).to_contain_text("clears /tmp when it reboots")
    tools.unroute("**/api/v1/toolcalls/summary*")
    tools.route("**/api/v1/toolcalls/summary*", lambda r: r.fulfill(status=500, json={"error": "internal_error", "detail": "OperationalError"}))
    tools.reload()
    expect(tools.get_by_role("alert")).to_contain_text("Could not load tool-call data")


def test_phone_width_has_no_horizontal_scroll(page: Page, live_console):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(live_console + "/#/tools")
    expect(page.get_by_role("heading", name="By agent model")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
