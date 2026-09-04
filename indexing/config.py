"""Load and normalize the indexing config (config/index_config.yaml)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml


@dataclasses.dataclass
class IndexConfig:
    working_dir: Path
    manifest_db: Path
    logs_dir: Path

    lancedb_dir: Path
    lancedb_table: str
    embed_dim: int

    fts5_table: str

    ollama_url: str
    embedding_model: str
    embed_batch_size: int
    embed_timeout_seconds: int

    @classmethod
    def load(cls, path: str | Path) -> "IndexConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        working_dir = Path(raw["working_dir"]).expanduser().resolve()

        return cls(
            working_dir=working_dir,
            manifest_db=working_dir / raw["manifest_db"],
            logs_dir=working_dir / raw["logs_dir"],
            lancedb_dir=working_dir / raw["lancedb_dir"],
            lancedb_table=raw["lancedb_table"],
            embed_dim=int(raw["embed_dim"]),
            fts5_table=raw["fts5_table"],
            ollama_url=raw["ollama_url"],
            embedding_model=raw["embedding_model"],
            embed_batch_size=int(raw["embed_batch_size"]),
            embed_timeout_seconds=int(raw["embed_timeout_seconds"]),
        )
