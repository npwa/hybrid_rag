"""T-DOC-1: every runbook or ticket the UI/API points at exists, and every failure cause has a runbook section."""
import re

from console.failures import CAUSES, RUNBOOK_CAUSES, cause_info
from tests.conftest import ROOT


def test_every_cause_has_a_runbook_section():
    text = (ROOT / RUNBOOK_CAUSES).read_text()
    headings = set(re.findall(r"^## `([a-z_]+)`", text, re.M))
    assert headings == set(CAUSES), headings ^ set(CAUSES)
    assert all(cause_info(c)["runbook"] == RUNBOOK_CAUSES for c in CAUSES)


def test_runbook_and_ticket_paths_mentioned_in_the_ui_source_exist():
    refs = set()
    for p in (ROOT / "console" / "web" / "src").rglob("*.tsx"):
        refs |= set(re.findall(r"Doc/(?:Runbooks|Issues)/[\w.-]+\.md", p.read_text()))
    assert refs, "UI mentions no runbooks"
    missing = [r for r in refs if not (ROOT / r).exists()]
    assert not missing, missing


def test_every_ticket_id_in_the_failure_map_has_a_file():
    for _, ticket in CAUSES.values():
        if ticket:
            assert (ROOT / "Doc" / "Issues" / f"{ticket}.md").exists()


def test_readme_mentions_the_console_and_points_at_existing_docs():
    readme = (ROOT / "README.md").read_text()
    for path in re.findall(r"`((?:Doc|scripts)/[\w./-]+\.(?:md|py|sh))`", readme):
        assert (ROOT / path).exists(), path
