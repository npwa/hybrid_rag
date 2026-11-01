"""HYR-04: Office lock files (~$...) are excluded at classification time."""
from types import SimpleNamespace

import pytest

from ingest.classify import classify
from ingest.config import Config


def cfg(**kw):
    base = dict(exclude_suffixes=("~", "#"), exclude_prefixes=("~$",), readme_todo_pattern="^(readme|todo)",
                include_extensions={"docx", "xlsx", "pdf", "txt"}, exclude_extensions={"zip"})
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize("name,expected", [
    ("~$Budget.xlsx", "excluded"), ("~$report.docx", "excluded"), ("~$README.txt", "excluded"),
    (".~lock.report.odt#", "excluded"), ("notes.txt~", "excluded"),
    ("Budget.xlsx", "include"), ("README.txt", "readme"), ("a~b.pdf", "include"), ("x$y.docx", "include"),
])
def test_lock_files_excluded_normal_files_untouched(name, expected):
    assert classify(name, cfg()) == expected


def test_prefixes_are_configurable_and_default_keeps_old_configs_working(tmp_path):
    assert classify("~$a.docx", cfg(exclude_prefixes=())) == "include"          # explicitly turned off
    from tests.conftest import ROOT
    import yaml
    raw = yaml.safe_load((ROOT / "config" / "ingest_config.example.yaml").read_text())
    raw.pop("exclude_prefixes")                                                  # an older config without the key
    raw["working_dir"] = str(tmp_path); raw["source_root"] = str(tmp_path)
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw))
    assert Config.load(p).exclude_prefixes == ("~$",)


def test_failed_readme_is_retried_but_other_failures_and_successes_are_reused():     # HYR-11
    from ingest.pipeline import _can_reuse
    row = lambda status, h="h": {"content_hash": h, "status": status}
    assert _can_reuse(row("extracted"), "h", "readme") is True
    assert _can_reuse(row("failed"), "h", "readme") is False          # converter may have been fixed
    assert _can_reuse(row("failed"), "h", "include") is True          # OCR failures are not re-run every time
    assert _can_reuse(row("extracted"), "other", "include") is False  # content changed
    assert _can_reuse(row("pending"), "h", "include") is False and _can_reuse(None, "h", "include") is False
