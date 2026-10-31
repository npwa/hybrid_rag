"""Run query.engine.answer_query against stubbed retrieval/embedding/generation so tests can
check logging without Ollama, LanceDB or real data."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import query.engine as engine
from query.config import QueryConfig
from query.generation import GenerationError
from indexing.embedder import EmbeddingError

ROOT = Path(__file__).resolve().parent.parent


def make_config(tmp: Path) -> QueryConfig:
    cfg = QueryConfig.load(ROOT / "config" / "query_config.yaml")
    cfg.logs_dir = tmp / "logs"
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.manifest_db = tmp / "manifest.db"
    sqlite3.connect(cfg.manifest_db).close()
    cfg.relevance_distance_threshold = 0.85
    cfg.relevance_min_hits = 1
    cfg.allow_general_knowledge_fallback = False
    return cfg


def _dense(n_close):
    rows = []
    for i in range(8):
        rows.append({"chunk_id": f"c{i}", "rel_path": f"Docs/file{i}.txt", "text": f"text {i}", "_distance": 0.5 + i * 0.01 if i < n_close else 0.95})
    return rows


def _sparse():
    return [{"chunk_id": f"c{i}", "rel_path": f"Docs/file{i}.txt", "text": f"text {i}", "score": -20.0 + i} for i in (1, 0, 9)]


CALLS: list = []   # (what, args) for every stubbed dependency call of the last run(): proves inputs unchanged


def run(monkeypatch, cfg, question, scenario, **kwargs):
    """scenario: answered | no_relevant | general | embed_error | generation_error"""
    CALLS.clear()

    def embed(_texts, _cfg):
        CALLS.append(("embed", list(_texts)))
        if scenario == "embed_error":
            raise EmbeddingError("timed out")
        return [[0.0] * 4]

    def gen(_system, _user, _cfg):
        CALLS.append(("generate", _system, _user))
        if scenario == "generation_error":
            raise GenerationError("boom")
        return "an answer"

    monkeypatch.setattr(engine, "embed_batch", embed)
    monkeypatch.setattr(engine, "open_table", lambda c: object())
    def dense(t, v, n):
        CALLS.append(("dense", list(v), n))
        return _dense(0 if scenario in ("no_relevant", "general") else 3)

    def sparse(conn, table, q, n):
        CALLS.append(("sparse", table, q, n))
        return _sparse()

    monkeypatch.setattr(engine, "dense_search", dense)
    monkeypatch.setattr(engine, "sparse_search", sparse)
    monkeypatch.setattr(engine, "generate_answer", gen)
    if scenario == "general":
        cfg.allow_general_knowledge_fallback = True
    return engine.answer_query(question, cfg, **kwargs)
