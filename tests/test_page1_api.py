"""Page 1 (Index health) API: T-P1-1 counts vs independent SQL, T-P1-3/4 failure classification,
T-P1-6 ANN gauge, masking."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from console.api import create_app
from console.failures import CAUSES, classify_problem, mask_message, mask_path


@pytest.mark.parametrize("status,msg,fn,expected", [
    ("failed", "OCR produced no text", "scan.png", "ocr_no_text"),
    ("failed", "OCR confidence 33.2 below failure threshold 40.0", "a.pdf", "ocr_below_threshold"),
    ("failed", "[Errno 13] Permission denied: '/x/y.pdf'", "y.pdf", "permission_denied"),
    ("failed", "could not read docx: Package not found at '/x/~$a.docx'", "~$a.docx", "lock_file"),
    ("failed", "anything", ".~lock.report.odt#", "lock_file"),
    ("failed", "could not read PDF pages: code=4: malformed page tree", "b.pdf", "damaged_file"),
    ("failed", "could not open image: cannot identify image file '/x'", "c.gif", "damaged_file"),
    ("failed", "convert_to_md.sh exited 1: xargs: unmatched single quote", "README", "conversion_error"),
    ("failed", "something nobody has seen", "d.pdf", "other"),
    ("failed", None, "e.pdf", "other"),
    ("ocr_low_confidence", None, "f.png", "ocr_low_confidence"),
    ("encrypted", None, "g.pdf", "encrypted"),
    ("empty", None, "h.txt", "empty"),
    ("warning_empty_conversion", "LibreOffice .doc->txt conversion produced <N chars", "i.doc", "empty_conversion"),
])
def test_classify_problem(status, msg, fn, expected):                              # T-P1-3
    assert classify_problem(status, msg, fn) == expected


def test_every_cause_has_label_and_known_ticket_file():                            # T-P1-4
    from tests.conftest import ROOT
    for cause, (label, ticket) in CAUSES.items():
        assert label
        if ticket:
            assert (ROOT / "Doc" / "Issues" / f"{ticket}.md").exists(), (cause, ticket)


def test_demo_summary_matches_independent_sql(client, demo_dir):                   # T-P1-1
    s = client.get("/api/v1/index/summary").json()
    c = sqlite3.connect(f"file:{demo_dir / 'manifest.db'}?mode=ro", uri=True)
    by = dict(c.execute("SELECT status, count(*) FROM files GROUP BY 1"))
    g = s["outcome_groups"]
    assert g["indexed"] == by["extracted"] + by["ocr_extracted"] + by["ocr_low_confidence"]
    assert g["failed"] == by["failed"] and g["skipped"] == by["skipped"]
    assert g["needs_attention"] == by["encrypted"] + by["empty"]
    assert sum(g.values()) == s["files_total"] == sum(by.values())
    assert s["attempted"] == s["files_total"] - g["skipped"]
    assert s["percent_failed"] == round(100 * g["failed"] / s["attempted"], 1)
    assert s["percent_indexed"] + s["percent_failed"] <= 100.0
    assert sum(r["total"] for r in s["files_by_type"]) == s["files_total"]            # nothing lost in the top-N cut
    assert s["chunks_by_embedding_status"] == {"embedded": s["chunks_total"]}


def test_problem_causes_sum_to_problem_files(client):
    s = client.get("/api/v1/index/summary").json()
    g = s["outcome_groups"]
    expected = g["failed"] + g["needs_attention"] + s["files_by_status"]["ocr_low_confidence"]
    assert sum(p["count"] for p in s["problems_by_cause"]) == expected
    causes = {p["cause"]: p for p in s["problems_by_cause"]}
    assert {"permission_denied", "ocr_no_text", "lock_file"} <= set(causes)
    assert causes["lock_file"]["ticket"] == "HYR-04" and causes["permission_denied"]["ticket_path"] == "Doc/Issues/HYR-03.md"


def test_failures_filter_sort_paginate(client):
    all_ = client.get("/api/v1/index/failures?limit=500").json()
    assert all_["total"] == len(all_["items"]) and all_["total"] > 50
    lock = client.get("/api/v1/index/failures?cause=lock_file").json()
    assert lock["total"] == 8 and all(i["rel_path"].split("/")[-1].startswith("~$") for i in lock["items"])
    pdf = client.get("/api/v1/index/failures?extension=pdf&limit=500").json()
    assert pdf["total"] > 0 and {i["extension"] for i in pdf["items"]} == {"pdf"}
    page1 = client.get("/api/v1/index/failures?limit=5&offset=0&sort=path").json()
    page2 = client.get("/api/v1/index/failures?limit=5&offset=5&sort=path").json()
    paths = [i["rel_path"] for i in page1["items"] + page2["items"]]
    assert paths == sorted(paths) and len(set(paths)) == 10
    desc = client.get("/api/v1/index/failures?limit=3&sort=path&desc=true").json()["items"]
    assert [i["rel_path"] for i in desc] == sorted([i["rel_path"] for i in all_["items"]], reverse=True)[:3]
    q = client.get("/api/v1/index/failures?q=Batch1").json()
    assert q["total"] > 0 and all("Batch1" in i["rel_path"] for i in q["items"])
    low = client.get("/api/v1/index/failures?status=ocr_low_confidence").json()
    assert all(i["ocr_confidence"] is not None and i["ocr_confidence"] > 40 for i in low["items"])   # FR-1.5


def test_failures_input_validation_is_json(client):
    assert client.get("/api/v1/index/failures?cause=bogus").status_code == 422
    assert client.get("/api/v1/index/failures?limit=0").status_code == 422
    assert client.get("/api/v1/index/failures?sort=evil").status_code == 422
    assert client.get("/api/v1/index/failures?q=%27%3B%20DROP%20TABLE%20files").json()["total"] == 0     # no injection


def test_masking_hides_paths_and_messages(demo_config):
    demo_config.mask_queries = True
    c = TestClient(create_app(demo_config), base_url="http://localhost")
    items = c.get("/api/v1/index/failures?limit=500").json()["items"]
    assert items and all(i["rel_path"].startswith("[masked-") for i in items)
    assert all("/demo/Documents" not in (i["error_message"] or "") for i in items)
    assert mask_path("a/b/Secret Report.pdf").endswith(".pdf") and "Secret" not in mask_path("a/b/Secret Report.pdf")
    assert mask_path("x/y.pdf") == mask_path("x/y.pdf") != mask_path("x/z.pdf")
    assert mask_message("Permission denied: '/home/u/f.pdf'") == "Permission denied: '[path masked]'"


def test_ann_gauge_states(demo_config):                                             # T-P1-6
    def state(threshold):
        demo_config.ann_threshold_chunks = threshold
        return TestClient(create_app(demo_config), base_url="http://localhost").get("/api/v1/index/summary").json()["ann"]
    n = state(10_000_000)["chunks"]
    assert state(10_000_000)["state"] == "ok"
    assert state(n * 2 - 1)["state"] == "approaching"            # at or above half of the threshold
    a = state(n)
    assert a["state"] == "needs_index" and a["ticket"] == "HYR-02" and a["has_ann_index"] is False
    assert a["percent_of_threshold"] == 100.0


def test_maintenance_runs_endpoint(client):
    r = client.get("/api/v1/maintenance/runs?limit=3").json()
    assert r["total"] == 5 and len(r["items"]) == 3
    assert r["items"][0]["result"] == "OK" and r["items"][0]["stages"]["index"] == "ok"
    full = client.get("/api/v1/maintenance/runs").json()["items"]
    assert full[-1]["result"] == "FAILED"                            # the old failure is last when newest-first
    assert client.get("/api/v1/maintenance/runs?limit=0").status_code == 422
