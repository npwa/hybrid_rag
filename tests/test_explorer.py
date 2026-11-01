"""Page 2 (Query explorer) backend: T-P2-1 .. T-P2-5, isolation from production logs, errors, masking."""
import hashlib
import logging
import re
import shutil

import pytest
from fastapi.testclient import TestClient

import query.engine as engine
from console import demo_embed, explorer
from console.api import create_app
from console.config import ConsoleConfig
from tests.conftest import ROOT

QUESTIONS = [
    "how do I reset the demo widget", "when does the ferry to the island leave", "which seedlings go in the raised bed",
    "what is the subnet of the guest network", "how much was the shipping on the last invoice",
    "what torque for the widget bracket", "list the compost schedule", "which museum is on the itinerary",
    "where did I store the firewall backup", "how do I calibrate the sensor", "warranty period for the gadget",
    "irrigation plan for the trellis", "router gateway address", "palette and varnish for the sketch",
    "battery firmware update", "booking luggage timetable", "subtotal quantity receipt", "dhcp switch firewall",
    "mulch seedlings compost", "widget",
]


@pytest.fixture()
def private_demo(demo_dir, tmp_path):
    dst = tmp_path / "demo"
    shutil.copytree(demo_dir, dst)
    return dst


@pytest.fixture()
def cfg(private_demo):
    return ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", demo=True, working_dir=private_demo)


@pytest.fixture()
def client(cfg):
    return TestClient(create_app(cfg), raise_server_exceptions=False, base_url="http://localhost")


def ask(client, q, **kw):
    r = client.post("/api/v1/explore", json={"query": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_fused_ranking_equals_production_fusion_detail_for_20_queries(cfg, monkeypatch, caplog):     # T-P2-1
    qcfg = explorer.build_query_config(cfg)
    monkeypatch.setattr(engine, "embed_batch", demo_embed.embed_batch)
    monkeypatch.setattr(engine, "generate_answer", lambda s, u, c: "stub")
    client = TestClient(create_app(cfg), base_url="http://localhost")
    caplog.set_level(logging.INFO, logger="query")
    compared = 0
    for q in QUESTIONS:
        caplog.clear()
        engine.answer_query(q, qcfg, caller="cli")
        detail = [r.getMessage() for r in caplog.records if "fusion detail" in r.getMessage()]
        ex = ask(client, q)
        if not ex["gate"]["relevant"]:
            assert not detail                                      # production would not have fused either
            continue
        (line,) = detail
        prod = re.findall(r"(?:: |; )(\S[^;]*?) branch=(\S+) rrf=([\d.]+)", line)
        assert [(p, b, float(s)) for p, b, s in prod] == [(f["rel_path"], f["branch"], f["rrf_score"]) for f in ex["fused"]], q
        compared += 1
    assert compared >= 15                                          # most demo questions are answerable


def test_legs_are_labelled_correctly(client):                                                         # T-P2-2
    seen = set()
    for q in QUESTIONS:
        d = ask(client, q)
        dense = {x["chunk_id"]: x for x in d["dense"]}
        sparse = {x["chunk_id"]: x for x in d["sparse"]}
        for f in d["fused"]:
            in_d, in_s = f["chunk_id"] in dense, f["chunk_id"] in sparse
            assert f["branch"] == "+".join(n for n, ok in (("dense", in_d), ("sparse", in_s)) if ok)
            assert (f["dense_rank"] == dense[f["chunk_id"]]["rank"]) if in_d else f["dense_rank"] is None
            assert (f["sparse_rank"] == sparse[f["chunk_id"]]["rank"]) if in_s else f["sparse_rank"] is None
            seen.add(f["branch"])
        assert [x["rank"] for x in d["dense"]] == list(range(1, len(d["dense"]) + 1))
        assert [x["distance"] for x in d["dense"]] == sorted(x["distance"] for x in d["dense"])      # ascending
        assert [x["bm25"] for x in d["sparse"]] == sorted(x["bm25"] for x in d["sparse"])             # best (lowest) first
        assert all(x["in_fused"] == (x["chunk_id"] in {f["chunk_id"] for f in d["fused"]}) for x in d["dense"] + d["sparse"])
    assert {"dense", "dense+sparse"} <= seen                       # (a sparse-only fused row is covered by the next test)


def test_min_hits_refusal_is_explained_and_matches_production(cfg, monkeypatch):                  # T-P2-3
    qcfg = explorer.build_query_config(cfg)
    base = ask(TestClient(create_app(cfg), base_url="http://localhost"), "how do I reset the demo widget")
    nearest, second = base["dense"][0]["distance"], base["dense"][1]["distance"]
    assert nearest < second
    qcfg.relevance_distance_threshold = (nearest + second) / 2     # exactly one hit under the threshold
    qcfg.relevance_min_hits = 2
    client = TestClient(create_app(cfg, query_config=qcfg), base_url="http://localhost")
    d = ask(client, "how do I reset the demo widget")
    g = d["gate"]
    assert g["relevant"] is False and g["hits"] == 1 and g["required_hits"] == 2
    assert g["would_pass_with_min_hits"]["1"] is True and g["would_pass_with_min_hits"]["2"] is False
    assert "Only 1 dense hit" in g["explanation"] and "needs 2" in g["explanation"] or "gate needs 2" in g["explanation"]
    assert g["production_outcome"] == "no_relevant"
    assert [x["passes_threshold"] for x in d["dense"][:3]] == [True, False, False]
    assert d["fused"] and d["sparse"]                              # the explorer still shows every stage
    monkeypatch.setattr(engine, "embed_batch", demo_embed.embed_batch)
    res = engine.answer_query("how do I reset the demo widget", qcfg)
    assert res.answer.startswith("I couldn't find anything relevant") and res.sources == []   # production agrees


def test_fallback_flag_changes_the_stated_outcome(cfg):
    qcfg = explorer.build_query_config(cfg)
    qcfg.allow_general_knowledge_fallback = True
    d = ask(TestClient(create_app(cfg, query_config=qcfg), base_url="http://localhost"), "who was wolfgang amadeus mozart")
    assert d["gate"]["relevant"] is False and d["gate"]["production_outcome"] == "general_knowledge"
    assert d["fused"] and "fallback is on" in d["gate"]["explanation"]      # every stage is still shown


def snapshot_logs(root):
    out = {}
    for p in sorted((root / "logs").glob("query_*")):
        out[p.name] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def test_explorer_never_touches_production_logs(cfg, private_demo):                                # T-P2-4
    client = TestClient(create_app(cfg), base_url="http://localhost")
    before = snapshot_logs(private_demo)
    (private_demo / "logs" / "query_2026-10-30.jsonl").write_text('{"x":1}\n')       # a production JSONL that must stay intact
    before = snapshot_logs(private_demo)
    for q in QUESTIONS[:10]:
        ask(client, q)
    assert snapshot_logs(private_demo) == before
    log = explorer.explorer_log_path(cfg)
    lines = log.read_text().splitlines()
    assert len(lines) == 10 and '"caller": "console-explorer"' in lines[0]
    assert not list((private_demo / "logs").glob("query_*")) == [] and log.parent.name == "explorer"


def test_generation_toggle(cfg, monkeypatch):                                                       # T-P2-5
    client = TestClient(create_app(cfg), base_url="http://localhost")
    d = ask(client, QUESTIONS[0])
    assert d["generated"] is False and d["answer"] is None and "generate_s" not in d["timings"]
    d = ask(client, QUESTIONS[0], generate=True)                      # demo mode: no model connected
    assert d["answer"] is None and "not available in demo mode" in d["generation_error"]

    real = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", working_dir=cfg.working_dir)   # demo=False
    qcfg = explorer.build_query_config(cfg)
    calls = []
    import query.generation as gen
    monkeypatch.setattr(gen, "generate_answer", lambda s, u, c: calls.append((s, u)) or "the answer")
    c2 = TestClient(create_app(real, embed=demo_embed.embed_batch, query_config=qcfg), base_url="http://localhost")
    d = ask(c2, QUESTIONS[0], generate=True)
    assert d["answer"] == "the answer" and d["generated"] and d["timings"]["generate_s"] >= 0 and len(calls) == 1
    assert "Source excerpts:" in calls[0][1] and QUESTIONS[0] in calls[0][1]
    assert ask(c2, "who was wolfgang amadeus mozart", generate=True)["answer"].startswith("I couldn't find")   # no model call
    assert len(calls) == 1
    def boom(s, u, c):
        raise gen.GenerationError("down")
    monkeypatch.setattr(gen, "generate_answer", boom)
    d = ask(c2, QUESTIONS[0], generate=True)
    assert d["answer"] is None and d["generation_error"] == "generation failed: down"


def test_validation_and_error_responses(cfg, monkeypatch):
    client = TestClient(create_app(cfg), raise_server_exceptions=False, base_url="http://localhost")
    assert client.post("/api/v1/explore", json={"query": ""}).status_code == 422
    assert client.post("/api/v1/explore", json={"query": "x" * 1001}).status_code == 422
    assert client.post("/api/v1/explore", json={}).status_code == 422
    r = client.post("/api/v1/explore", json={"query": "   "})
    assert r.status_code == 422 and r.json()["error"] == "bad_request"
    assert client.get("/api/v1/explore").status_code in (404, 405)       # POST-only (404 when the UI mount catches it)

    from indexing.embedder import EmbeddingError
    def fail(texts, c=None):
        raise EmbeddingError("could not reach Ollama")
    r = TestClient(create_app(cfg, embed=fail), base_url="http://localhost").post("/api/v1/explore", json={"query": "widget"})
    assert r.status_code == 502 and r.json() == {"error": "embedding_failed", "detail": "could not reach Ollama"}

    assert explorer._busy.acquire(blocking=False)
    try:
        r = client.post("/api/v1/explore", json={"query": "widget"})
        assert r.status_code == 429 and r.json()["error"] == "busy"
    finally:
        explorer._busy.release()
    assert client.post("/api/v1/explore", json={"query": "widget"}).status_code == 200


def test_missing_index_gives_503_not_a_crash(cfg, tmp_path):
    real = ConsoleConfig.load(ROOT / "config" / "console_config.example.yaml", working_dir=tmp_path / "nothing")
    r = TestClient(create_app(real), base_url="http://localhost").post("/api/v1/explore", json={"query": "widget"})
    assert r.status_code == 503 and r.json()["error"] == "source_unavailable"


def test_masking_hides_paths_and_excerpts(cfg):
    cfg.mask_queries = True
    d = ask(TestClient(create_app(cfg), base_url="http://localhost"), QUESTIONS[0])
    rows = d["dense"] + d["sparse"] + d["fused"]
    assert rows and all(r["rel_path"].startswith("[masked-") and r["excerpt"] == "[masked]" for r in rows)


def test_response_has_no_raw_vectors_and_bounded_excerpts(client):
    d = ask(client, QUESTIONS[0])
    text = str(d)
    assert "vector" not in text and max(len(r["excerpt"]) for r in d["dense"]) <= explorer.EXCERPT_CHARS + 1
    assert set(d["timings"]) >= {"embed_s", "dense_s", "sparse_s", "fuse_s", "total_s"}
    assert d["settings"]["rrf_k"] == 60 and d["settings"]["top_k_fused"] == 8


def test_explorer_does_not_change_the_data_directory(cfg, private_demo):
    from tests.test_readonly import snapshot
    client = TestClient(create_app(cfg), base_url="http://localhost")
    before = {k: v for k, v in snapshot(private_demo).items() if not k.startswith("logs/explorer")}
    for q in QUESTIONS[:5]:
        ask(client, q)
    after = {k: v for k, v in snapshot(private_demo).items() if not k.startswith("logs/explorer")}
    assert after == before


def test_demo_embedder_properties():
    a, b = demo_embed.embed_text("widget reset"), demo_embed.embed_text("reset the widget")
    assert len(a) == demo_embed.DIM and abs(sum(x * x for x in a) - 1) < 1e-9
    assert a == b                                                  # stop words ignored, word order irrelevant
    assert demo_embed.embed_text("") == demo_embed.embed_text("the and of")   # no tokens: unit fallback, never NaN


def test_sparse_only_and_dense_only_rows_are_labelled(cfg, monkeypatch):                          # T-P2-2 (all three shapes)
    from query.engine import Retrieval
    dense = [{"chunk_id": "a", "rel_path": "A.txt", "text": "alpha", "_distance": 0.4},
             {"chunk_id": "b", "rel_path": "B.txt", "text": "beta", "_distance": 0.5}]
    sparse = [{"chunk_id": "c", "rel_path": "C.txt", "text": "gamma", "score": -9.0},
              {"chunk_id": "a", "rel_path": "A.txt", "text": "alpha", "score": -8.0}]
    from query.fusion import rrf_fuse
    fused = rrf_fuse([dense, sparse], k=60, top_k=8, list_names=["dense", "sparse"])
    monkeypatch.setattr(engine, "retrieve", lambda q, c, full=False, embed=None: Retrieval([0.0], dense, True, 2, sparse, fused, {"embed_s": 0.0}))
    d = ask(TestClient(create_app(cfg), base_url="http://localhost"), "x")
    by = {f["chunk_id"]: f for f in d["fused"]}
    assert by["a"]["branch"] == "dense+sparse" and by["a"]["dense_rank"] == 1 and by["a"]["sparse_rank"] == 2
    assert by["b"]["branch"] == "dense" and by["b"]["sparse_rank"] is None and by["b"]["sparse_bm25"] is None
    assert by["c"]["branch"] == "sparse" and by["c"]["dense_rank"] is None and by["c"]["dense_distance"] is None
    assert [x["also_sparse"] for x in d["dense"]] == [True, False] and [x["also_dense"] for x in d["sparse"]] == [False, True]
