"""M0 exit criteria: the demo dataset is deterministic, complete and contains no real data
(T-PRIV-1), and its manifest has the same schema as the real one."""
import re
import sqlite3
from pathlib import Path

import pytest

from ingest.manifest import SCHEMA
from tests.conftest import build_demo


def ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def dump(demo: Path) -> dict:
    c = ro(demo / "manifest.db")
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1,2").fetchall() for t in ("files", "chunks")}
    out["logs"] = {p.name: p.read_bytes() for p in sorted((demo / "logs").rglob("*")) if p.is_file()}
    return out


def test_deterministic_for_same_seed(demo_dir, tmp_path):
    again = build_demo(tmp_path / "again")
    assert dump(demo_dir) == dump(again)


def test_different_seed_differs(demo_dir, tmp_path):
    other = build_demo(tmp_path / "other", seed=1)
    assert dump(demo_dir)["files"] != dump(other)["files"]


def test_manifest_schema_matches_real_schema(demo_dir):
    c = ro(demo_dir / "manifest.db")
    real = sqlite3.connect(":memory:")
    real.executescript(SCHEMA)
    for table in ("files", "chunks"):
        cols = lambda con: [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        assert cols(c) == cols(real)


def test_all_statuses_and_failure_causes_present(demo_dir):
    c = ro(demo_dir / "manifest.db")
    statuses = {r[0] for r in c.execute("SELECT DISTINCT status FROM files")}
    assert {"extracted", "ocr_extracted", "ocr_low_confidence", "failed", "skipped", "encrypted", "empty"} <= statuses
    errs = [r[0] for r in c.execute("SELECT error_message FROM files WHERE status='failed'")]
    for needle in ("Permission denied", "OCR produced no text", "damaged", "OCR confidence", "lock file"):
        assert any(needle in e for e in errs), needle
    assert c.execute("SELECT count(*) FROM files WHERE filename LIKE '~$%'").fetchone()[0] > 0


def test_chunks_fts_and_vectors_agree(demo_dir):
    import lancedb
    c = ro(demo_dir / "manifest.db")
    n = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert n == c.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    tbl = lancedb.connect(str(demo_dir / "lancedb")).open_table("chunks")
    assert tbl.count_rows() == n
    assert len(tbl.to_arrow().column("vector")[0]) == 768
    assert c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'widget'").fetchone()[0] > 0


def test_maintenance_log_has_old_failure_then_ok(demo_dir):
    ends = [l for l in (demo_dir / "logs" / "maintenance.log").read_text().splitlines() if "maintenance run end" in l]
    assert "FAILED" in ends[0] and all("OK" in l for l in ends[1:])        # last line decides (T-P1-2)


def test_query_logs_use_real_formats(demo_dir):
    text = "\n".join(p.read_text() for p in (demo_dir / "logs").glob("query_*.log"))
    assert re.search(r"INFO     QUERY '.+' -> \d+ sources, [\d.]+s \[", text)
    assert "not relevant, fallback disabled" in text and "QUERY_EMBED_FAILED" in text
    assert "fusion detail:" in text and "generation:" in text


def test_agent_logs_have_tool_milestones_and_config_summary(demo_dir):
    agent = demo_dir / "logs" / "agent"
    assert "tool_execution_started" in "".join(p.read_text() for p in agent.glob("openclaw-*.log"))
    assert (agent / "config-summary.json").exists()


PERSONAL = [r"\+1\d{10}", r"almassy", r"npalmass", r"/home/", r"192\.168\.", r"@almassy", r"nick@", r"maryse",
            r"npabot", r"mars"]


def test_no_personal_markers_anywhere(demo_dir):
    """T-PRIV-1: nothing real may leak into the demo tree (text files and the SQLite dump)."""
    blobs = [p.read_text(errors="ignore") for p in demo_dir.rglob("*") if p.is_file() and p.suffix in (".log", ".json", ".txt")]
    c = ro(demo_dir / "manifest.db")
    blobs.append(repr(c.execute("SELECT * FROM files").fetchall()))
    blobs.append(repr(c.execute("SELECT text, rel_path FROM chunks").fetchall()))
    joined = "\n".join(blobs)
    for pat in PERSONAL:
        assert not re.search(pat, joined, re.I), pat
