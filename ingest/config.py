"""Load and normalize the ingestion config (config/ingest_config.yaml)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml


@dataclasses.dataclass
class Config:
    source_root: Path
    working_dir: Path
    extracted_text_dir: Path
    manifest_db: Path
    logs_dir: Path

    exclude_hidden: bool

    include_extensions: set[str]
    exclude_extensions: set[str]
    exclude_suffixes: tuple[str, ...]

    readme_todo_pattern: str
    convert_to_md_script: Path

    pdf_text_min_chars: int

    soffice_binary: str
    soffice_timeout_seconds: int
    empty_conversion_min_chars: int

    ocr_confidence_high: float
    ocr_confidence_low: float
    tesseract_lang: str

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        working_dir = Path(raw["working_dir"]).expanduser().resolve()

        return cls(
            source_root=Path(raw["source_root"]).expanduser(),
            working_dir=working_dir,
            extracted_text_dir=working_dir / raw["extracted_text_dir"],
            manifest_db=working_dir / raw["manifest_db"],
            logs_dir=working_dir / raw["logs_dir"],
            exclude_hidden=bool(raw["exclude_hidden"]),
            include_extensions={e.lower() for e in raw["include_extensions"]},
            exclude_extensions={e.lower() for e in raw["exclude_extensions"]},
            exclude_suffixes=tuple(raw["exclude_suffixes"]),
            readme_todo_pattern=raw["readme_todo_pattern"],
            convert_to_md_script=(working_dir / raw["convert_to_md_script"]),
            pdf_text_min_chars=int(raw["pdf_text_min_chars"]),
            soffice_binary=raw["soffice_binary"],
            soffice_timeout_seconds=int(raw["soffice_timeout_seconds"]),
            empty_conversion_min_chars=int(raw["empty_conversion_min_chars"]),
            ocr_confidence_high=float(raw["ocr_confidence_high"]),
            ocr_confidence_low=float(raw["ocr_confidence_low"]),
            tesseract_lang=raw["tesseract_lang"],
        )
