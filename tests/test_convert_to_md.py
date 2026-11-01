"""HYR-11: convert_to_md.sh must not die on quote characters in text."""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "convert_to_md.sh"


def convert(tmp_path, text, name="README"):
    f = tmp_path / name
    f.write_text(text)
    r = subprocess.run([str(SCRIPT), name], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    return r, (tmp_path / (name + ".md"))


def test_apostrophe_before_a_colon_does_not_abort_the_conversion(tmp_path):
    r, out = convert(tmp_path, "Intro\n\nHere's a detailed breakdown of the causes:\n\nIt's fine. Don't panic: really.\n")
    assert r.returncode == 0, r.stderr
    assert "detailed breakdown" in out.read_text()


def test_double_quotes_and_backslash_before_a_colon(tmp_path):
    r, out = convert(tmp_path, 'The "quoted" part: x\nback\\slash key: y\n')
    assert r.returncode == 0, r.stderr
    assert out.exists()


def test_status_line_with_apostrophe(tmp_path):
    r, out = convert(tmp_path, "DONE, it's finished\nTODO: fix Bob's thing\n")
    assert r.returncode == 0, r.stderr


def test_ordinary_key_value_still_works(tmp_path):
    r, out = convert(tmp_path, "Name:   Foo Bar\n")
    assert r.returncode == 0 and "Foo Bar" in out.read_text()
