"""png/jpg/jpeg/bmp/gif OCR extraction — §6."""
from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from ingest.config import Config
from ingest.extractors import ExtractionResult


def _preprocess(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    return ImageOps.autocontrast(gray)


def extract_image(path: Path, config: Config) -> ExtractionResult:
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        return ExtractionResult(status="failed", error_message=f"could not open image: {e}")

    try:
        processed = _preprocess(img)
        data = pytesseract.image_to_data(
            processed, lang=config.tesseract_lang, output_type=pytesseract.Output.DICT
        )
    except Exception as e:
        return ExtractionResult(status="failed", error_message=f"OCR failed: {e}")

    words = [w for w in data["text"] if w.strip()]
    confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
    text = " ".join(words)
    avg_conf = sum(confs) / len(confs) if confs else 0.0

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
