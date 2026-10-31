"""UI smoke tests for Page 2, the query explorer (FR-2.x), in a real browser against the demo dataset."""
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

with sync_playwright() as _p:
    _chromium_ok = __import__("os").path.exists(_p.chromium.executable_path)
pytestmark = pytest.mark.skipif(not _chromium_ok, reason="run: python -m playwright install chromium")

Q = "how do I reset the demo widget"


@pytest.fixture()
def explorer(page: Page, live_console):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(live_console + "/#/explorer")
    page.errors = errors
    return page


def explore(page, question=Q):
    page.get_by_label("Question").fill(question)
    page.get_by_role("button", name="Explore").click()


def test_explore_shows_gate_three_lists_and_timings(explorer: Page):
    expect(explorer.get_by_role("heading", name="Query explorer")).to_be_visible()
    expect(explorer.get_by_role("button", name="Explore")).to_be_disabled()            # nothing typed yet
    explore(explorer)
    expect(explorer.get_by_role("heading", name=re.compile("Relevance gate"))).to_contain_text("PASSED")
    expect(explorer.get_by_role("heading", name=re.compile("^Dense"))).to_be_visible()
    expect(explorer.get_by_role("heading", name=re.compile("^Keyword"))).to_be_visible()
    fused = explorer.locator("section", has=explorer.get_by_role("heading", name=re.compile("^Fused ranking")))
    expect(fused.locator("ol.hits li")).to_have_count(8)
    expect(fused.locator("ol.hits li").first).to_contain_text("rrf ")
    dense = explorer.locator("section", has=explorer.get_by_role("heading", name=re.compile("^Dense")))
    expect(dense.locator("ol.hits li")).to_have_count(20)
    expect(explorer.get_by_label("Timings")).to_contain_text("embed")
    assert explorer.errors == []


def test_fused_order_matches_api(explorer: Page, live_console):
    import json, urllib.request
    req = urllib.request.Request(live_console + "/api/v1/explore", data=json.dumps({"query": Q}).encode(),
                                 headers={"Content-Type": "application/json"})
    api = json.load(urllib.request.urlopen(req))
    explore(explorer)
    fused = explorer.locator("section", has=explorer.get_by_role("heading", name=re.compile("^Fused ranking")))
    expect(fused.locator("ol.hits li .path")).to_have_text([f["rel_path"] for f in api["fused"]])


def test_irrelevant_question_shows_failed_gate_and_why(explorer: Page):
    explorer.get_by_role("button", name="who was wolfgang amadeus mozart").click()
    gate = explorer.get_by_role("heading", name=re.compile("Relevance gate"))
    expect(gate).to_contain_text("NOT PASSED")
    expect(explorer.get_by_text("would not call the language model")).to_be_visible()
    expect(explorer.get_by_text("No keyword matches")).to_be_visible()
    expect(explorer.get_by_text(re.compile(r"What if the required hits were"))).to_be_visible()


def test_generation_checkbox_disabled_in_demo(explorer: Page):
    box = explorer.get_by_role("checkbox")
    expect(box).to_be_disabled()
    expect(explorer.get_by_text("not available in demo mode")).to_be_visible()


def test_excerpt_expands(explorer: Page):
    explore(explorer)
    first = explorer.locator("ol.hits li").first
    first.get_by_text("excerpt").click()
    expect(first.locator("p.excerpt")).to_contain_text("Demo document")


def test_errors_are_shown(explorer: Page):
    explorer.route("**/api/v1/explore", lambda r: r.fulfill(status=502, json={"error": "embedding_failed", "detail": "could not reach Ollama"}))
    explore(explorer)
    expect(explorer.get_by_role("alert")).to_contain_text("could not reach Ollama")
    explorer.unroute("**/api/v1/explore")
    explorer.route("**/api/v1/explore", lambda r: r.fulfill(status=429, json={"error": "busy", "detail": "busy"}))
    explore(explorer)
    expect(explorer.get_by_role("alert")).to_contain_text("Another exploration is running")


def test_enter_key_submits_and_phone_width_has_no_horizontal_scroll(page: Page, live_console):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(live_console + "/#/explorer")
    page.get_by_label("Question").fill(Q)
    page.get_by_label("Question").press("Enter")
    expect(page.get_by_role("heading", name=re.compile("Relevance gate"))).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
