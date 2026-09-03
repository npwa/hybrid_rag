# Step 3 Requirements: Chunking

Consumes Step 1/2's output (`manifest.db` + `extracted_text/`) and produces retrieval-sized
chunks with source-traceable metadata, ready for Step 4 (embedding + BM25 indexing). No
embedding, no vector DB, no BM25 index gets built in this step — pure text splitting only.

---

## 1. Scope & Environment

- **Input:** `manifest.db` (`files` table) + `extracted_text/`, both produced by Step 1/2.
- **Working directory:** `~/work/hybrid_rag/` (same as Step 1/2).
- Runs on the desktop, CPU-only — pure text processing, no GPU or network needed.
- **Eligible source rows:** `status IN ('extracted', 'ocr_extracted', 'ocr_low_confidence')`
  — the only statuses that have a real `extracted_text_path`. In the current real corpus
  that's 639 + 414 + 285 = **1,338 files**.
- Everything else (`skipped`, `unclassified`, `empty`, `encrypted`, `failed`,
  `warning_empty_conversion`, `deleted`) has no text and is not chunked.

## 2. Storage (proposed)

Add a `chunks` table directly to the existing `manifest.db` rather than a separate
database — same corpus, keeps `file_id` joins trivial, and SQLite handles this scale
(low thousands of files → an estimated 10-40K chunks) without issue.

```
~/work/hybrid_rag/
├── manifest.db          # existing (Step 1/2) + new `chunks` table (this step)
├── extracted_text/      # existing (Step 1/2), read-only input to this step
└── config/
    └── chunk_config.yaml   # chunk size, overlap, per-type rules
```

## 3. Chunking rules by content type

This is the core design problem for this step — the same "normalization before
retrieval" theme the README calls out for Excel/PNG at the ingestion layer has a direct
analogue here: markdown, plain text, and spreadsheet-dump text all need different
splitting logic.

### 3a. Plain text
(`.txt` output from txt/text/PDF/docx/legacy doc, and OCR'd images/scanned PDFs)

- Paragraph-aware recursive splitting: break on blank lines / paragraph boundaries first,
  then sentence boundaries, only falling back to a hard character cut if a single
  paragraph exceeds the chunk size on its own.
- Target chunk size: **~1,500 characters (~300–400 tokens), ~15% overlap (~200 chars)**.
  Character-based rather than a specific tokenizer for now, since the embedding model
  isn't chosen yet (that's Step 4) — worth revisiting with a proper tokenizer once it is.

### 3b. Markdown output
(`.md` from README/TODO conversion via `convert_to_md.sh`, or passthrough)

- These already carry YAML frontmatter (`title`, `type`, `created`, `tags`) followed by
  `##`-level date/section headings.
- Strip the frontmatter before chunking, but promote its `tags` into chunk metadata —
  Step 1 already parsed this into `files.tags`; reuse it, don't re-parse the frontmatter.
- Split primarily on `##` heading boundaries (one chunk per section where reasonable),
  falling back to the paragraph splitter within an oversized section. Never split a
  heading from the paragraph that immediately follows it.

### 3c. Spreadsheet output
(`.txt` from xlsx/xls, formatted by Step 1 as `## Sheet: <name>` + tab-separated rows)

- Split on `## Sheet:` boundaries first — never merge two sheets into one chunk.
- Within a sheet, group rows so a chunk stays under the size target, but **repeat the
  header row (the first row after the `## Sheet:` line) at the top of every chunk** for
  that sheet, so each chunk is independently interpretable without needing a neighboring
  chunk for column context.
- Carry the sheet name (already in `files.sheet_names` from Step 1) into chunk metadata
  as `sheet_name` — the specific sheet this chunk came from.

### 3d. Low-confidence OCR
(`status='ocr_low_confidence'`)

- Chunk normally, but propagate `ocr_confidence` onto every chunk from that file, so
  Step 5 (retrieval) can down-weight or flag these results rather than silently treating
  them the same as clean-extracted text.

## 4. Proposed `chunks` table schema

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | TEXT (PK) | sha256 of `file_id` + `chunk_index` |
| `file_id` | TEXT | FK → `files.file_id` |
| `chunk_index` | INTEGER | position within the file, 0-based |
| `text` | TEXT | the chunk content |
| `char_start` / `char_end` | INTEGER | offsets into the extracted-text file, for traceability/highlighting back to source |
| `source_content_hash` | TEXT | copy of `files.content_hash` at chunk-creation time — the idempotency key (§5) |
| `rel_path`, `category`, `extension`, `tags`, `sheet_name`, `ocr_used`, `ocr_confidence` | — | denormalized from `files`, so Step 4/5 can filter/weight without a join |
| `embedding_status` | TEXT | `pending` / `embedded` / `deleted` — bridge column Step 4 updates; this step only ever writes `pending` (or `deleted`, see §5) |
| `created_at` | TIMESTAMP | |

Required indexes (not optional at any real scale — see §8):

```sql
CREATE INDEX idx_chunks_file_id ON chunks(file_id);
CREATE INDEX idx_chunks_embedding_status ON chunks(embedding_status);
```

`idx_chunks_file_id` is what makes "delete this file's existing chunks" (§5) an indexed
lookup instead of a full table scan; `idx_chunks_embedding_status` is what makes Step 4's
"find all `pending` chunks" an indexed lookup instead of scanning every row on every run.

## 5. Idempotency

Mirrors Step 1's pattern (§8 of `step-1-requirements.md`):

- On each run, compare `files.content_hash` (current) against the `source_content_hash`
  stored on that file's existing chunk rows.
  - Unchanged → no-op, skip re-chunking.
  - Changed, or no chunks exist yet → delete that file's existing chunk rows, regenerate.
- `status='deleted'` files (Step 1 marks these rather than removing rows): mark their
  chunks `embedding_status='deleted'` rather than physically deleting them, mirroring
  Step 1's history-preservation choice. Step 4/5 filter these out at query time, but the
  record survives for traceability.

## 6. Error handling & logging

- One structured log per run, same pattern as Step 1 (`logs/chunk_<timestamp>.log`).
- A malformed or unexpectedly oversized single file must never abort the whole run — log
  and skip that file, continue with the rest.
- End-of-run summary: files chunked, chunks created, chunks marked deleted (stale
  sources), files skipped (no eligible status).

## 7. Step 3 Deliverable (handoff boundary)

Output: the `chunks` table fully populated for every eligible file, with
`embedding_status='pending'` on every new/changed row. No embeddings, no vector DB, no
BM25 index — that's Step 4. Step 3 never modifies `extracted_text/` or original source
files; it only reads them.

## 8. Scalability (target: 1M documents / 500GB)

Revisiting the volume estimate at the scale actually being designed for, rather than the
current ~2,500-file corpus: 1,000,000 files / 500GB is ~400x the current file count and
~294x the current byte count. Using the current corpus's text-to-source ratio (21MB
extracted from 1.7GB source, ≈1.2%) as a low bound and a more text-native mix as a high
bound (~5%), extracted text volume lands somewhere around **6–25GB**, which at the
~1,275-net-char chunk size works out to roughly **5–20 million chunks** — meaningfully
different from a "few hundred thousand" small-scale estimate, and the number that should
actually drive design decisions here and in Step 4.

At that row count:

- **The indexes in §4 are not optional** — without `idx_chunks_file_id`, invalidating one
  changed file's chunks (§5) becomes a full scan of a 5–20M-row table on every changed
  file, every run.
- **Batch commits, not one per file/chunk.** Step 1's code was updated to open
  `manifest.db` with `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL` and commit in
  batches (every ~200 rows) rather than once per row — committing every row was the
  dominant SQLite bottleneck at large file counts (one fsync per row). Step 3's
  implementation should follow the same pattern for `chunks` inserts.
- **Chunking should run in a process pool, same pattern as Step 1.** Text splitting is
  CPU-bound per file and embarrassingly parallel across files. Step 1's pipeline now
  follows a specific concurrency model worth reusing directly: worker processes do the
  expensive, stateless work (here: splitting one file's text into chunk records) and
  return results; the main process is the sole writer to `manifest.db`, consuming results
  as they complete and batching commits. This avoids any SQLite multi-writer contention
  while still using all available cores.
- **Bounded memory regardless of corpus size.** Don't load the full file list or full
  `chunks` table into memory to decide what needs re-chunking — query per file
  (`idx_chunks_file_id` again) or process in a bounded streaming window, not an
  all-at-once load. At 5–20M chunk rows a naive "load everything into a Python dict"
  approach (which Step 1's manifest-claims registry does, safely, at the current ~2,500
  file scale) would start to cost real memory — gigabytes rather than megabytes — so
  Step 3 shouldn't reuse that exact pattern at this row count.

None of this changes the schema or the chunking rules in §3–§4 — it's entirely about how
the implementation writes to SQLite and how much work happens in parallel.

---

## Open Questions

1. **Chunk size/overlap** (~1,500 chars / 15%) is a reasonable starting default, but
   should really be tuned against the actual embedding model's context window once Step 4
   picks one — may be worth revisiting with a proper token count at that point rather than
   a character-count proxy.
2. **Markdown section-splitting granularity** — some `##` sections in the converted notes
   are one-liners (e.g. a single `**Status:**` line) and others run long. Worth checking
   real output for whether very short sections should merge with a neighbor rather than
   becoming their own (nearly empty) chunk.
