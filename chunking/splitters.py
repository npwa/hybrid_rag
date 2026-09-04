"""Per-content-type text splitting — step-3-requirements.md §3.

Every splitter returns a list of ChunkSpan. For plain text and Markdown, `text`
is always exactly `full_text[start:end]` — the span *is* the chunk. Spreadsheet
chunks are the one exception: per §3c, every chunk after the first repeats the
sheet's header row, so `text` there is a synthesized string (header + rows)
that doesn't correspond to a single contiguous slice of the source; `start`/
`end` in that case still bound the real row-data region the chunk covers, for
traceability, even though they don't reproduce `text` verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ChunkSpan:
    start: int
    end: int
    text: str
    sheet_name: str | None = None


_PARA_RE = re.compile(r"\n\s*\n")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_MD_HEADING_RE = re.compile(r"^## .*$", re.MULTILINE)
_SHEET_RE = re.compile(r"^## Sheet: .*$", re.MULTILINE)


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    pos = 0
    for m in _PARA_RE.finditer(text):
        if m.start() > pos and text[pos:m.start()].strip():
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text) and text[pos:].strip():
        spans.append((pos, len(text)))
    return spans


def _presplit_oversized(text: str, spans: list[tuple[int, int]], target: int) -> list[tuple[int, int]]:
    """Any span longer than `target` gets broken down further: first by sentence,
    and if a single "sentence" is still too long (e.g. unpunctuated OCR noise), by
    a hard character cut — the documented last-resort fallback (§3a)."""
    result: list[tuple[int, int]] = []
    for s, e in spans:
        if e - s <= target:
            result.append((s, e))
            continue
        sub = text[s:e]
        sent_spans = []
        pos = 0
        for m in _SENT_RE.finditer(sub):
            if sub[pos:m.start()].strip():
                sent_spans.append((s + pos, s + m.start()))
            pos = m.end()
        if pos < len(sub) and sub[pos:].strip():
            sent_spans.append((s + pos, s + len(sub)))
        for ss, se in sent_spans:
            if se - ss <= target:
                result.append((ss, se))
            else:
                pos2 = ss
                while pos2 < se:
                    end2 = min(pos2 + target, se)
                    result.append((pos2, end2))
                    pos2 = end2
    return result


def _pack_spans(spans: list[tuple[int, int]], target: int, overlap: int) -> list[tuple[int, int]]:
    """Greedily pack pre-split spans (each already <= target) into chunks, carrying
    trailing spans from one chunk into the start of the next as approximate overlap
    (paragraph/sentence-granularity, not exact-character — §3a)."""
    if not spans:
        return []
    chunks: list[tuple[int, int]] = []
    cur = [spans[0]]
    cur_len = spans[0][1] - spans[0][0]
    for sp in spans[1:]:
        slen = sp[1] - sp[0]
        if cur_len + slen > target and cur:
            chunks.append((cur[0][0], cur[-1][1]))
            carry: list[tuple[int, int]] = []
            carry_len = 0
            for prev in reversed(cur):
                plen = prev[1] - prev[0]
                if carry_len + plen > overlap:
                    break
                carry.insert(0, prev)
                carry_len += plen
            cur = carry + [sp]
            cur_len = sum(x[1] - x[0] for x in cur)
        else:
            cur.append(sp)
            cur_len += slen
    if cur:
        chunks.append((cur[0][0], cur[-1][1]))
    return chunks


def _plain_text_spans(text: str, target: int, overlap: int) -> list[tuple[int, int]]:
    spans = _paragraph_spans(text)
    spans = _presplit_oversized(text, spans, target)
    return _pack_spans(spans, target, overlap)


def chunk_plain_text(text: str, target: int, overlap: int) -> list[ChunkSpan]:
    return [ChunkSpan(s, e, text[s:e]) for s, e in _plain_text_spans(text, target, overlap)]


def chunk_markdown(text: str, target: int, overlap: int, min_section: int) -> list[ChunkSpan]:
    fm_match = _FRONTMATTER_RE.match(text)
    body_start = fm_match.end() if fm_match else 0
    body = text[body_start:]

    headings = list(_MD_HEADING_RE.finditer(body))
    if not headings:
        # No section structure at all — just a plain-text document in Markdown clothing.
        return [ChunkSpan(body_start + s, body_start + e, text[body_start + s:body_start + e])
                for s, e in _plain_text_spans(body, target, overlap)]

    bounds: list[tuple[int, int]] = []
    if headings[0].start() > 0 and body[:headings[0].start()].strip():
        bounds.append((0, headings[0].start()))
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        bounds.append((h.start(), end))

    # Merge sections shorter than min_section into the previous section (§ Open Questions
    # #2 — a lone one-line "## ..." section with nothing under it shouldn't become its
    # own near-empty chunk).
    merged: list[tuple[int, int]] = []
    for s, e in bounds:
        if merged and (merged[-1][1] - merged[-1][0]) < min_section:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    result: list[tuple[int, int]] = []
    for s, e in merged:
        if e - s <= target:
            result.append((s, e))
        else:
            for a, b in _plain_text_spans(body[s:e], target, overlap):
                result.append((s + a, s + b))

    return [ChunkSpan(body_start + s, body_start + e, text[body_start + s:body_start + e])
            for s, e in result]


def chunk_spreadsheet(text: str, target: int) -> list[ChunkSpan]:
    sheets = list(_SHEET_RE.finditer(text))
    if not sheets:
        # Shouldn't normally happen (Step 1 always emits a "## Sheet:" header), but
        # don't crash on a malformed/edge-case file — fall back to plain-text chunking.
        return chunk_plain_text(text, target, overlap=0)

    result: list[ChunkSpan] = []
    for i, m in enumerate(sheets):
        s = m.start()
        e = sheets[i + 1].start() if i + 1 < len(sheets) else len(text)
        sheet_text = text[s:e]
        sheet_name = m.group(0)[len("## Sheet: "):].strip()

        lines = sheet_text.split("\n")
        header_line = lines[0] if len(lines) > 0 else ""
        col_header = lines[1] if len(lines) > 1 else ""
        data_lines = lines[2:]

        if not any(l.strip() for l in data_lines):
            # Header-only sheet (no rows) — one chunk, verbatim.
            result.append(ChunkSpan(s, e, sheet_text, sheet_name=sheet_name))
            continue

        prefix = f"{header_line}\n{col_header}\n"
        # Track each data line's absolute (start, end) offset in the source text.
        pos = s + len(header_line) + 1 + len(col_header) + 1
        line_spans = []
        for line in data_lines:
            line_spans.append((pos, pos + len(line)))
            pos += len(line) + 1

        chunk_lines: list[str] = []
        chunk_start = None
        chunk_end = None
        cur_len = len(prefix)
        for (ls, le), line in zip(line_spans, data_lines):
            llen = (le - ls) + 1
            if chunk_lines and cur_len + llen > target:
                result.append(ChunkSpan(
                    chunk_start, chunk_end, prefix + "\n".join(chunk_lines), sheet_name=sheet_name,
                ))
                chunk_lines = []
                cur_len = len(prefix)
                chunk_start = None
            if chunk_start is None:
                chunk_start = ls
            chunk_lines.append(line)
            chunk_end = le
            cur_len += llen
        if chunk_lines:
            result.append(ChunkSpan(
                chunk_start, chunk_end, prefix + "\n".join(chunk_lines), sheet_name=sheet_name,
            ))

    return result


def split_text(text: str, *, extension: str, category: str, target: int, overlap: int, min_section: int) -> list[ChunkSpan]:
    """Dispatch by content type — mirrors ingest.extractors.extract()'s dispatch-by-
    extension pattern (§3)."""
    if category == "readme" or extension == "md":
        return chunk_markdown(text, target, overlap, min_section)
    if extension in ("xlsx", "xls"):
        return chunk_spreadsheet(text, target)
    return chunk_plain_text(text, target, overlap)
