"""PDF extraction — §6: text-layer first, OCR fallback for scanned pages,
encrypted PDFs are a hard exclusion (no decrypt attempt)."""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

from ingest.config import Config
from ingest.extractors import ExtractionResult

_OCR_DPI_ZOOM = 300 / 72  # render at ~300dpi for OCR


def extract_pdf(path: Path, config: Config) -> ExtractionResult:
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        return ExtractionResult(status="failed", error_message=f"could not open PDF: {e}")

    try:
        if doc.is_encrypted:
            # Confirmed hard exclusion (§6) — no decryption attempt, no password lookup.
            return ExtractionResult(status="encrypted")

        try:
            text_parts = [page.get_text() for page in doc]
        except Exception as e:
            # A malformed/corrupt PDF can make MuPDF raise mid-walk (e.g. "malformed page
            # tree") — one bad file must never abort the run (§7), so fail just this file.
            return ExtractionResult(status="failed", error_message=f"could not read PDF pages: {e}")

        text = "\n\n".join(text_parts)

        if len(text.strip()) >= config.pdf_text_min_chars:
            return ExtractionResult(status="extracted", text=text)

        try:
            return _ocr_pdf(doc, config)
        except Exception as e:
            return ExtractionResult(status="failed", error_message=f"OCR fallback failed: {e}")
    finally:
        doc.close()


def _ocr_pdf(doc: "pymupdf.Document", config: Config) -> ExtractionResult:
    page_texts: list[str] = []
    confidences: list[float] = []
    matrix = pymupdf.Matrix(_OCR_DPI_ZOOM, _OCR_DPI_ZOOM)

    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        data = pytesseract.image_to_data(
            img, lang=config.tesseract_lang, output_type=pytesseract.Output.DICT
        )
        words = [w for w in data["text"] if w.strip()]
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]

        page_texts.append(" ".join(words))
        confidences.extend(confs)

    text = "\n\n".join(page_texts)
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    if not text.strip():
        return ExtractionResult(
            status="failed", ocr_used=True, ocr_confidence=avg_conf,
            error_message="OCR produced no text",
        )

    if avg_conf >= config.ocr_confidence_high:
        return ExtractionResult(status="ocr_extracted", text=text, ocr_used=True, ocr_confidence=avg_conf)

    if avg_conf >= config.ocr_confidence_low:
        return ExtractionResult(status="ocr_low_confidence", text=text, ocr_used=True, ocr_confidence=avg_conf)

    return ExtractionResult(
        status="failed", ocr_used=True, ocr_confidence=avg_conf,
        error_message=f"OCR confidence {avg_conf:.1f} below failure threshold {config.ocr_confidence_low}",
    )
