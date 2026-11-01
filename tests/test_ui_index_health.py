"""UI smoke tests for Page 1 (T-UI-1, FR-1.x) with a real browser against the demo dataset.
Skipped automatically when the web UI is not built or Chromium is not installed
(.venv/bin/python -m playwright install chromium)."""
import json
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

with sync_playwright() as _p:                      # skip (not error) when Chromium has not been downloaded
    _chromium_ok = __import__("os").path.exists(_p.chromium.executable_path)
pytestmark = pytest.mark.skipif(not _chromium_ok, reason="run: python -m playwright install chromium")


@pytest.fixture()
def app(page: Page, live_console):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(live_console)
    page.errors = errors
    return page


def api(live_console, path):
    import urllib.request
    return json.load(urllib.request.urlopen(live_console + path))


def test_page_renders_without_errors_and_shows_status(app: Page, live_console):          # T-UI-1
    expect(app).to_have_title("Hybrid RAG console")
    expect(app.get_by_role("heading", name="Files", exact=True)).to_be_visible()
    expect(app.get_by_role("status")).to_contain_text("Console ok")
    expect(app.get_by_role("status")).to_contain_text("Last maintenance OK")
    expect(app.get_by_text("Showing synthetic demo data")).to_be_visible()
    assert app.errors == []


def test_headline_numbers_match_api(app: Page, live_console):
    s = api(live_console, "/api/v1/index/summary")
    stat = lambda label: app.locator(".stat", has_text=label).locator(".stat-value")
    expect(stat("Files seen")).to_have_text(f"{s['files_total']:,}")
    expect(stat("Indexed")).to_have_text(f"{s['outcome_groups']['indexed']:,}")
    expect(stat("Failed")).to_have_text(f"{s['outcome_groups']['failed']:,}")
    expect(app.locator(".stat", has_text="Failed")).to_contain_text(f"{s['percent_failed']:.1f}% of attempted")


def test_causes_table_filters_the_file_list(app: Page):                                  # FR-1.4
    row = app.get_by_role("table", name="Problems by cause").get_by_role("row", name=re.compile("Office lock file"))
    expect(row).to_be_visible()
    expect(row).to_contain_text("HYR-04")
    row.get_by_role("button", name="Show files").click()
    files = app.get_by_role("table").filter(has_text="Ticket").last.locator("tbody tr")
    expect(files).to_have_count(8)
    for i in range(8):
        expect(files.nth(i).locator("td.path")).to_contain_text("~$")
    expect(app.get_by_text("1–8 of 8")).to_be_visible()
    app.get_by_role("button", name="Clear filters").click()
    expect(app.get_by_text(re.compile(r"1–50 of \d+"))).to_be_visible()


def test_sorting_and_paging(app: Page):
    table = app.get_by_role("table").filter(has_text="Ticket").last
    first = table.locator("tbody tr").first.locator("td.path")
    before = first.inner_text()
    table.get_by_role("button", name=re.compile("^File")).click()      # was sorted ascending -> now descending
    expect(table.get_by_role("columnheader", name=re.compile("^File"))).to_have_attribute("aria-sort", "descending")
    expect(first).not_to_have_text(before)
    app.get_by_role("button", name="Next").click()
    expect(app.get_by_text(re.compile(r"51–\d+ of"))).to_be_visible()
    expect(app.get_by_role("button", name="Previous")).to_be_enabled()


def test_ann_gauge_and_type_bars_present(app: Page):                                      # FR-1.7
    expect(app.get_by_role("meter")).to_be_visible()
    expect(app.get_by_text("Ticket HYR-02")).to_be_visible()
    expect(app.get_by_role("table", name="Files by type and outcome")).to_be_visible()


def test_stale_index_banner(app: Page, live_console):                                    # FR-1.6
    body = api(live_console, "/api/v1/health")
    body["maintenance"]["stale"] = True
    body["maintenance"]["last_run"]["result"] = "FAILED"
    app.route("**/api/v1/health", lambda r: r.fulfill(json=body))
    app.reload()
    expect(app.get_by_role("alert")).to_contain_text("The index looks stale")
    expect(app.get_by_role("alert")).to_contain_text("last maintenance run FAILED")


def test_api_error_is_shown_not_a_blank_page(app: Page):
    app.route("**/api/v1/index/summary", lambda r: r.fulfill(status=503, json={"error": "source_unavailable", "detail": "manifest not found"}))
    app.reload()
    expect(app.get_by_role("alert")).to_contain_text("Could not load the index summary")
    expect(app.get_by_role("alert")).to_contain_text("manifest not found")


def test_api_down_shows_status_error(app: Page):
    app.route("**/api/v1/health", lambda r: r.abort())
    app.reload()
    expect(app.get_by_role("alert").first).to_contain_text("Cannot reach the console API")


def test_every_page_is_built(app: Page):
    for link, heading in (("Query explorer", "Query explorer"), ("Tool-call monitor", "Tool-call monitor"), ("Query analytics", "Query analytics")):
        app.get_by_role("link", name=link).click()
        expect(app.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(app.get_by_text("Not built yet")).to_have_count(0)
    app.get_by_role("link", name="Index health").click()
    expect(app.get_by_role("heading", name="Files", exact=True)).to_be_visible()


def test_no_horizontal_scroll_on_a_phone(page: Page, live_console):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(live_console)
    expect(page.get_by_role("heading", name="Files", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_dark_mode_renders(browser, live_console):
    ctx = browser.new_context(color_scheme="dark")
    p = ctx.new_page()
    p.goto(live_console)
    expect(p.get_by_role("heading", name="Files", exact=True)).to_be_visible()
    bg = p.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg != "rgb(246, 247, 249)"
    ctx.close()


def test_rows_per_page_offers_50_100_500_and_is_remembered(app: Page):
    size = app.get_by_label("Rows per page")
    expect(size.locator("option")).to_have_text(["50", "100", "500"])
    expect(size).to_have_value("50")
    app.get_by_role("button", name="Next").click()
    size.select_option("100")
    expect(app.get_by_text(re.compile(r"1–\d+ of \d+"))).to_be_visible()          # back on the first page
    expect(app.get_by_role("button", name="Previous")).to_be_disabled()
    table = app.get_by_role("table").filter(has_text="Ticket").last
    total = int(re.search(r"of (\d+)", app.locator(".pager span").inner_text()).group(1))
    expect(table.locator("tbody tr")).to_have_count(min(100, total))
    app.reload()
    expect(app.get_by_label("Rows per page")).to_have_value("100")
