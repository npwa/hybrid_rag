"""UI smoke tests for Page 3, query analytics (FR-3.x), in a real browser against the demo dataset."""
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
def analytics(page: Page, live_console):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(live_console + "/#/analytics")
    page.errors = errors
    return page


def stats(live_console, days=30):
    return json.load(urllib.request.urlopen(f"{live_console}/api/v1/queries/stats?days={days}"))


def test_numbers_equal_the_api(analytics: Page, live_console):
    d = stats(live_console)
    t = d["totals"]
    expect(analytics.get_by_role("heading", name="Query analytics", exact=True)).to_be_visible()
    stat = lambda label: analytics.locator(".stat").filter(has=analytics.locator(".stat-label", has_text=re.compile(f"^{re.escape(label)}")))
    expect(stat("Questions").locator(".stat-value")).to_have_text(str(t["queries"]))
    expect(stat("No relevant result").locator(".stat-value")).to_have_text(f"{d['rates']['no_relevant']:.1f}%")
    expect(stat("Errors")).to_contain_text(f"{t['by_outcome']['error']} failed")
    expect(stat("Slow")).to_contain_text(f"{t['slow']} of {t['timed']} timed")
    assert analytics.errors == []


def test_charts_are_present_and_labelled(analytics: Page):
    expect(analytics.get_by_role("img", name=re.compile("Queries per day"))).to_be_visible()
    expect(analytics.get_by_role("img", name=re.compile("Median and 95th percentile"))).to_be_visible()


def test_tabs_switch_between_slow_no_result_and_errors(analytics: Page, live_console):
    slow = json.load(urllib.request.urlopen(live_console + "/api/v1/queries/slow?kind=slow&days=30&limit=15"))
    table = analytics.get_by_role("table", name="Queries: slow")
    expect(table.locator("tbody tr")).to_have_count(min(15, slow["total"]))
    analytics.get_by_role("tab", name="No relevant result").click()
    expect(analytics.get_by_role("table", name="Queries: no_result")).to_be_visible()
    analytics.get_by_role("tab", name="Errors").click()
    expect(analytics.get_by_role("table", name="Queries: error")).to_contain_text("could not reach Ollama")


def test_recurring_questions_and_terms_listed(analytics: Page, live_console):
    d = stats(live_console)
    rows = analytics.get_by_role("table", name="Recurring questions").locator("tbody tr")
    expect(rows).to_have_count(len(d["top_queries"]))
    expect(rows.first).to_contain_text(d["top_queries"][0]["query"])
    expect(analytics.get_by_label("Common words")).to_contain_text(d["top_terms"][0]["term"])


def test_period_selector_changes_the_data(analytics: Page, live_console):
    week = stats(live_console, 7)["totals"]["queries"]
    analytics.get_by_label("Period").select_option("7")
    expect(analytics.locator(".stat").filter(has=analytics.locator(".stat-label", has_text=re.compile("^Questions$"))).locator(".stat-value")).to_have_text(str(week))


def test_no_horizontal_scroll_on_a_phone(analytics: Page):
    analytics.set_viewport_size({"width": 390, "height": 800})
    analytics.reload()
    expect(analytics.get_by_role("heading", name="Query analytics", exact=True)).to_be_visible()
    assert analytics.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
