"""Load and normalize the chunking config (config/chunk_config.yaml)."""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import yaml


@dataclasses.dataclass
class ChunkConfig:
    working_dir: Path
    extracted_text_dir: Path
    manifest_db: Path
    logs_dir: Path

    chunk_target_chars: int
    chunk_overlap_chars: int
    min_section_chars: int

    max_workers: int

    @classmethod
    def load(cls, path: str | Path) -> "ChunkConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        working_dir = Path(raw["working_dir"]).expanduser().resolve()

        return cls(
            working_dir=working_dir,
            extracted_text_dir=working_dir / raw["extracted_text_dir"],
            manifest_db=working_dir / raw["manifest_db"],
            logs_dir=working_dir / raw["logs_dir"],
            chunk_target_chars=int(raw["chunk_target_chars"]),
            chunk_overlap_chars=int(raw["chunk_overlap_chars"]),
            min_section_chars=int(raw["min_section_chars"]),
            max_workers=int(raw["max_workers"]) if raw.get("max_workers") else (os.cpu_count() or 4),
        )
