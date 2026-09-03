"""Per-file-type extraction — step-1-requirements.md §6.

Every extractor returns an ExtractionResult; the caller (ingest/pipeline.py)
is responsible for writing `.text` under extracted_text/ and updating the
manifest row. Extractors never raise for expected failure modes (encrypted
PDF, empty conversion, low-confidence OCR, etc.) — they encode those as a
`status` instead, so one bad file never aborts the run (§7).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

from ingest.config import Config


@dataclasses.dataclass
class ExtractionResult:
    status: str
    text: Optional[str] = None
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    sheet_names: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    error_message: Optional[str] = None


def extract(path: Path, category: str, extension: str, config: Config) -> ExtractionResult:
    from ingest.extractors import image, office, pdf, text

    if category == "readme":
        return text.extract_readme(path, config)

    if extension in ("txt", "text"):
        return text.extract_plain_text(path)

    if extension == "md":
        # Whitelisted Markdown that isn't a README/TODO match — already-normalized
        # content, passthrough with no conversion (§4a).
        return text.extract_plain_text(path)

    if extension == "pdf":
        return pdf.extract_pdf(path, config)

    if extension == "docx":
        return office.extract_docx(path)

    if extension == "doc":
        return office.extract_doc_legacy(path, config)

    if extension == "xlsx":
        return office.extract_xlsx(path)

    if extension == "xls":
        return office.extract_xls_legacy(path, config)

    if extension in ("png", "jpg", "jpeg", "bmp", "gif"):
        return image.extract_image(path, config)

    return ExtractionResult(status="failed", error_message=f"No extractor for extension '{extension}'")
