"""Load and normalize the query-engine config (config/query_config.yaml)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml


@dataclasses.dataclass
class QueryConfig:
    working_dir: Path
    manifest_db: Path
    logs_dir: Path

    lancedb_dir: Path
    lancedb_table: str
    fts5_table: str

    # Same attribute names as indexing.config.IndexConfig on purpose — lets
    # indexing.embedder.embed_batch() be called with a QueryConfig directly, no adapter.
    ollama_url: str
    embedding_model: str
    embed_timeout_seconds: int

    generation_model: str
    num_ctx: int
    think: bool
    generation_timeout_seconds: int

    top_n_dense: int
    top_n_sparse: int
    rrf_k: int
    top_k_fused: int

    # Opt-in general-knowledge fallback (query/relevance.py) — off by default. See
    # Doc/step-5-requirements.md for why strict document-grounding is the default.
    allow_general_knowledge_fallback: bool
    relevance_distance_threshold: float
    relevance_min_hits: int

    http_host: str
    http_port: int

    @classmethod
    def load(cls, path: str | Path) -> "QueryConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        working_dir = Path(raw["working_dir"]).expanduser().resolve()

        return cls(
            working_dir=working_dir,
            manifest_db=working_dir / raw["manifest_db"],
            logs_dir=working_dir / raw["logs_dir"],
            lancedb_dir=working_dir / raw["lancedb_dir"],
            lancedb_table=raw["lancedb_table"],
            fts5_table=raw["fts5_table"],
            ollama_url=raw["ollama_url"],
            embedding_model=raw["embedding_model"],
            embed_timeout_seconds=int(raw["embed_timeout_seconds"]),
            generation_model=raw["generation_model"],
            num_ctx=int(raw["num_ctx"]),
            think=bool(raw["think"]),
            generation_timeout_seconds=int(raw["generation_timeout_seconds"]),
            top_n_dense=int(raw["top_n_dense"]),
            top_n_sparse=int(raw["top_n_sparse"]),
            rrf_k=int(raw["rrf_k"]),
            top_k_fused=int(raw["top_k_fused"]),
            allow_general_knowledge_fallback=bool(raw.get("allow_general_knowledge_fallback", False)),
            relevance_distance_threshold=float(raw.get("relevance_distance_threshold", 0.7)),
            relevance_min_hits=int(raw.get("relevance_min_hits", 2)),
            http_host=raw["http_host"],
            http_port=int(raw["http_port"]),
        )
