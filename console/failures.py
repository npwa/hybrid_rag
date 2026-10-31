"""Failure-cause classification for Page 1 (FR-1.4, FR-1.5) and ticket linkage.

The causes come from the real manifest (error_message texts and statuses seen on the
development corpus); anything unrecognised is 'other', never dropped. Tickets are the
Doc/Issues/HYR-nn.md files; the map is code so the UI can show the id next to a cause."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# status -> outcome group used by the summary (FR-1.1)
INDEXED_STATUSES = ("extracted", "ocr_extracted", "ocr_low_confidence")
PROBLEM_STATUSES = ("failed", "ocr_low_confidence", "encrypted", "empty", "warning_empty_conversion")

RUNBOOK_CAUSES = "Doc/Runbooks/index-failure-causes.md"   # one section per cause id (checked by tests)

CAUSES = {
    "ocr_no_text":          ("Image or scan with no recognisable text", "HYR-06"),
    "ocr_below_threshold":  ("OCR confidence below the failure threshold", "HYR-06"),
    "ocr_low_confidence":   ("Indexed, but OCR confidence is low", "HYR-06"),
    "permission_denied":    ("Permission denied reading the file", "HYR-03"),
    "lock_file":            ("Office lock file (~$...)", "HYR-04"),
    "damaged_file":         ("Damaged or unreadable file", "HYR-06"),
    "conversion_error":     ("Conversion script error", "HYR-06"),
    "encrypted":            ("Encrypted file", None),
    "empty_conversion":     ("Conversion produced almost no text", None),
    "empty":                ("Empty file", None),
    "other":                ("Other / unrecognised", None),
}


def classify_problem(status: str, error_message: str | None, filename: str) -> str:
    msg = (error_message or "").lower()
    if filename.startswith("~$") or filename.startswith(".~lock."):
        return "lock_file"
    if status == "ocr_low_confidence":
        return "ocr_low_confidence"
    if status == "encrypted":
        return "encrypted"
    if status == "empty":
        return "empty"
    if status == "warning_empty_conversion":
        return "empty_conversion"
    if "permission denied" in msg or "errno 13" in msg:
        return "permission_denied"
    if "ocr produced no text" in msg:
        return "ocr_no_text"
    if "below failure threshold" in msg:
        return "ocr_below_threshold"
    if "convert_to_md.sh" in msg or "xargs" in msg:
        return "conversion_error"
    if any(k in msg for k in ("malformed", "cannot identify image", "not a zip file", "package not found",
                              "damaged", "cannot open document", "could not read", "could not open")):
        return "damaged_file"
    return "other"


def cause_info(cause: str) -> dict:
    label, ticket = CAUSES[cause]
    return {"cause": cause, "label": label, "ticket": ticket,
            "ticket_path": f"Doc/Issues/{ticket}.md" if ticket else None,
            "runbook": RUNBOOK_CAUSES}


_PATH_IN_MSG = re.compile(r"(['\"])(/[^'\"]*)\1")


def mask_path(rel_path: str) -> str:
    """Privacy masking (FR-3.6/P3): keep the extension, replace the name with a short stable hash."""
    ext = rel_path.rsplit(".", 1)[-1] if "." in rel_path.rsplit("/", 1)[-1] else ""
    h = hashlib.sha1(rel_path.encode()).hexdigest()[:8]
    return f"[masked-{h}]" + (f".{ext}" if ext else "")


def mask_message(msg: str | None) -> str | None:
    return None if msg is None else _PATH_IN_MSG.sub(lambda m: f"{m.group(1)}[path masked]{m.group(1)}", msg)


@dataclass
class OutcomeGroups:
    indexed: int = 0
    failed: int = 0
    needs_attention: int = 0
    skipped: int = 0
    other: int = 0


def outcome_group(status: str) -> str:
    if status in INDEXED_STATUSES:
        return "indexed"
    if status == "failed":
        return "failed"
    if status in ("encrypted", "empty", "warning_empty_conversion"):
        return "needs_attention"
    if status == "skipped":
        return "skipped"
    return "other"
