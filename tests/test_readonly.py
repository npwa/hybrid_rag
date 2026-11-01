"""T-RO-1..4 and T-ISO-1: the console cannot modify data and holds no locks."""
import hashlib
import os
import shutil
import sqlite3
import stat

import pytest

from console.readers.lance_reader import LanceReadOnly
from console.readers.sqlite_ro import is_read_only, open_ro


WAL_SIDE_FILES = ("-wal", "-shm")   # SQLite coordination files; a WAL database cannot be read without them


def snapshot(root):
    """(relative path -> (size, mtime_ns, sha1)) for every data file below root. The SQLite WAL side
    files are excluded: readers of a WAL database create/touch them, but they never change data
    (the main database file and everything else are still compared byte for byte)."""
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.endswith(WAL_SIDE_FILES):
            st = p.stat()
            snap[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, hashlib.sha1(p.read_bytes()).hexdigest())
    return snap


@pytest.fixture()
def private_demo(demo_dir, tmp_path):
    """A throwaway copy, so mode/permission games never touch the shared session dataset."""
    dst = tmp_path / "demo"
    shutil.copytree(demo_dir, dst)
    return dst


def test_manifest_writes_fail_and_file_unchanged(demo_dir):                   # T-RO-1
    before = snapshot(demo_dir)
    conn = open_ro(demo_dir / "manifest.db")
    for stmt in ("INSERT INTO files (file_id) VALUES ('x')", "UPDATE files SET status='x'", "DELETE FROM chunks",
                 "CREATE TABLE t (x)", "DROP TABLE files", "PRAGMA journal_mode=DELETE"):
        try:
            conn.execute(stmt)
            conn.commit()
            changed = True
        except sqlite3.Error:
            changed = False
        assert not changed or stmt.startswith("PRAGMA"), stmt
    assert is_read_only(conn)
    conn.close()
    assert snapshot(demo_dir) == before


def test_lance_wrapper_has_no_write_surface_and_dir_unchanged(demo_dir):       # T-RO-2
    before = snapshot(demo_dir / "lancedb")
    reader = LanceReadOnly(demo_dir / "lancedb", "chunks")
    assert reader.count_rows() > 0 and reader.vector_dim() == 768 and reader.has_ann_index() is False
    public = {n for n in dir(reader) if not n.startswith("_")}
    assert public == {"count_rows", "vector_dim", "has_ann_index"}
    assert not any(w in n for n in public for w in ("add", "delete", "merge", "create", "drop", "update"))
    assert snapshot(demo_dir / "lancedb") == before


def test_full_api_session_leaves_data_directory_untouched(demo_config, demo_dir):   # T-RO-4
    from fastapi.testclient import TestClient
    from console.api import create_app
    before = snapshot(demo_dir)
    c = TestClient(create_app(demo_config), raise_server_exceptions=False, base_url="http://localhost")
    for path in ("/api/v1/health", "/api/v1/index/summary", "/api/v1/health", "/", "/api/v1/nope", "/docs"):
        c.get(path)
    assert snapshot(demo_dir) == before


def test_console_works_with_unwritable_data_and_creates_nothing(private_demo):  # T-RO-3
    from fastapi.testclient import TestClient
    from console.api import create_app
    from console.config import ConsoleConfig
    from tests.conftest import ROOT
    for p in [private_demo, *private_demo.rglob("*")]:
        mode = p.stat().st_mode
        os.chmod(p, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        files_before = {str(p) for p in private_demo.rglob("*") if not p.name.endswith(WAL_SIDE_FILES)}
        cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True, working_dir=private_demo)
        c = TestClient(create_app(cfg), raise_server_exceptions=False, base_url="http://localhost")
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/api/v1/index/summary").status_code == 200
        assert {str(p) for p in private_demo.rglob("*") if not p.name.endswith(WAL_SIDE_FILES)} == files_before
    finally:
        for p in [private_demo, *private_demo.rglob("*")]:
            os.chmod(p, p.stat().st_mode | stat.S_IWUSR)


def test_console_holds_no_lock_another_process_can_write(demo_config, private_demo):   # T-ISO-1 (lock part)
    from fastapi.testclient import TestClient
    from console.api import create_app
    from console.config import ConsoleConfig
    from tests.conftest import ROOT
    cfg = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True, working_dir=private_demo)
    c = TestClient(create_app(cfg), raise_server_exceptions=False, base_url="http://localhost")
    assert c.get("/api/v1/index/summary").status_code == 200
    writer = sqlite3.connect(private_demo / "manifest.db", timeout=1)            # the pipeline's write path
    writer.execute("UPDATE files SET last_processed='2099-01-01T00:00:00' WHERE rowid=1")
    writer.commit()
    writer.close()
    assert c.get("/api/v1/index/summary").status_code == 200


def test_console_does_not_import_serving_modules():                            # C1: separate process, no shared code paths
    import subprocess, sys
    code = "import sys, console.api, console.health; bad=[m for m in ('query.server','query.mcp_server','query.engine') if m in sys.modules]; print(bad)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"
