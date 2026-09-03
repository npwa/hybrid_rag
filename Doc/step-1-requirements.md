# Step 1 Requirements: Data Preparation & Ingestion / File Discovery

Local RAG project — Documents folder (~1.7GB) → Signal → OpenClaw → local Ollama.
This document is the detailed spec for Step 1 only: discovery, classification, and
extraction of source files into normalized text + a manifest. No chunking, embedding,
or indexing happens in this step — that's Step 2+.

---

## 1. Scope & Environment

- **Source root:** `/mnt/mars/nick/Documents` (recursive)
- **Working directory:** `~/work/hybrid_rag/`
- **Existing tool to integrate:** `~/work/hybrid_rag/convert_to_md.sh` (README preprocessing — see §6)
- Runs on the desktop (has Ollama, more compute) rather than the OpenClaw VM, since extraction/OCR is CPU/GPU-heavy and doesn't need network access.

## 2. Directory Layout (proposed)

```
~/work/hybrid_rag/
├── manifest.db          # SQLite manifest (see §5)
├── extracted_text/      # normalized output, mirrors source subfolder structure
│   ├── <relative-path>/<original-filename>.txt   # plain-text extraction (txt/pdf/doc/xls/image OCR)
│   └── <relative-path>/<stem>.md                 # Markdown output (README/TODO, whitelisted .md) — see §4b
├── logs/
│   └── ingest_<timestamp>.log
└── config/
    └── ingest_config.yaml   # thresholds, password lookups, exclusion overrides
```

## 3. File Walk Rules

- Recurse through all subfolders of `/mnt/mars/nick/Documents`.
- **Do not follow symlinks** (avoid loops / escaping the Documents tree). Log any symlinks encountered but skip them.
- **Exclude hidden files/directories** (dotfiles, `.git`, `.DS_Store`, etc.) by default — confirmed. Expose as a config toggle in case any need to be included later, but off by default.
- **Skip zero-byte files** — log as `empty`, don't error.
- Handle **permission errors** per-file: log and continue, don't abort the whole walk.

## 4. Classification Rules

### 4a. Include — whitelist by extension (case-insensitive)
`png jpg jpeg bmp gif txt text md pdf xls xlsx doc docx`

`.md` was added to the whitelist (was previously only reachable via the README rule below): a plain, non-README/TODO Markdown file is included directly, no conversion — same passthrough handling as an already-normalized `README.md`.

### 4b. Include — README/TODO files
**Confirmed:** filename matches `README*` **or `TODO*`** (case-insensitive), e.g. `README`, `Readme.txt`, `readme.md`, `TODO`, `Todo.txt`. TODO-named files get identical treatment to README-named files — same pattern-matching, same processing.

Processing rule:
- If the file **already has a `.md` extension** → treat as already-normalized Markdown, no conversion needed, include directly.
- Otherwise → run `convert_to_md.sh <filename>` before indexing (see §6 for the script's contract).

**Tags:** files processed through the `convert_to_md.sh` conversion path have their `tags: [...]` line parsed out of the script's generated frontmatter (which already merges the source's `-*- rag-tags:... -*-` header with the script's own medical/legal auto-tags) and stored in the manifest's `tags` column (§5). Passthrough `.md` files (README or plain) are not parsed for tags, since they never go through the script.

**Output filename:** unlike the plain-text extraction path (§2, `<original-filename>.txt`, which stays collision-free by construction because it retains the full original filename), Markdown output drops the original extension and uses `<stem>.md` — e.g. `README.txt` → `README.md`, bare `README` → `README.md`. Dropping the extension makes a same-directory collision possible (e.g. a folder containing both `README` and `README.txt`); the first file (by walk order) gets the canonical `<stem>.md`, and each subsequent colliding file gets `<stem>-2.md`, `<stem>-3.md`, etc. Assignments are stable across re-runs — an already-processed file keeps its slot rather than being renumbered.

### 4c. Exclude
- Filenames ending in `~` or `#` (editor backup/lock files)
- Extensions (case-insensitive): `c crt css dat dict el ged gpg gz h heic htm html ipynb js key log mov mp3 mp4 org out ovpn pfx pict psd py rtf sh tgz tiff tsv wav zip`

### 4d. Unclassified (new category — gap in original outline)
Any file that matches **neither** the whitelist nor the exclusion list (e.g. an extension not anticipated, or no extension at all and not a README match) should be logged to a separate `unclassified` bucket in the manifest rather than silently skipped or silently processed. You review this list periodically and either add the extension to the include/exclude config or leave it.

## 5. Manifest

**Format:** SQLite database (`manifest.db`) rather than flat JSON/CSV — needed for querying by status, updating rows on re-run, and tracking incremental changes without rewriting the whole file. Can be exported to JSONL on demand for inspection.

### Proposed schema (`files` table)

| Field | Type | Notes |
|---|---|---|
| `file_id` | TEXT (PK) | sha256 of absolute path (stable identifier even if content changes) |
| `abs_path` | TEXT | full path |
| `rel_path` | TEXT | path relative to `/mnt/mars/nick/Documents` (useful as retrieval metadata, e.g. `Finance/Tax/Tax-2024/...`) |
| `filename` | TEXT | |
| `extension` | TEXT | lowercased |
| `size_bytes` | INTEGER | |
| `mtime` | TIMESTAMP | source file's last-modified time |
| `content_hash` | TEXT | sha256 of file contents — used for change detection across runs |
| `category` | TEXT | `include` / `readme` / `excluded` / `unclassified` |
| `status` | TEXT | `pending` / `extracted` / `ocr_extracted` / `warning_empty_conversion` / `failed` / `encrypted` / `empty` / `skipped` |
| `extracted_text_path` | TEXT | path under `extracted_text/`, null if not yet processed |
| `ocr_used` | BOOLEAN | whether OCR fallback was needed |
| `sheet_names` | TEXT | JSON list, Excel files only |
| `tags` | TEXT | JSON list — parsed from `convert_to_md.sh`'s frontmatter for README/TODO conversions (§4b), null otherwise |
| `error_message` | TEXT | populated on failure |
| `last_processed` | TIMESTAMP | |

### Change detection (new — not in original outline)
On re-run: compare `content_hash` (not just mtime, which can change without content changing, e.g. after a backup restore) against the stored value. Only re-extract files that are new or whose hash changed. Files no longer present on disk should be marked `deleted` rather than removed from the manifest outright, so history/traceability is preserved.

## 6. Extraction — Tools Needed Per Type

| Type | Primary tool | Fallback / notes |
|---|---|---|
| `txt`, `text`, README files | Direct read + encoding detection (`charset-normalizer` or `chardet`) | Source files may not be UTF-8; don't assume |
| README specifically | `convert_to_md.sh` | **Confirmed contract:** takes one `filename` argument, writes output to `filename.md`. Implementation should check the exit code and confirm `filename.md` was actually created before marking the file `extracted`; treat a nonzero exit or missing output as `failed` |
| `pdf` (text layer present) | `PyMuPDF` (fitz) or `pdftotext` (poppler-utils) | |
| `pdf` (scanned / no text layer) | OCR fallback: `ocrmypdf` or `pytesseract` on rasterized pages | **Important for this project:** tax documents are frequently scanned. Detect by extracting text first — if result is empty or below a length threshold, route to OCR automatically rather than reporting failure |
| `pdf` (password-protected) | Attempt with `PyMuPDF`/`pikepdf` to detect encryption | **Confirmed:** encrypted PDFs are excluded from processing, logged with `status=encrypted`. No decryption attempt or password lookup — this is a hard exclusion, not a fallback path |
| `doc`, `docx` | `python-docx` for `.docx`; legacy `.doc` via **LibreOffice headless** (`soffice --headless --convert-to txt`) | **Validated, adopted** — see §6a for test results and the known empty-output caveat |
| `xls`, `xlsx` | `openpyxl` for `.xlsx`; legacy `.xls` via **LibreOffice headless** (`soffice --headless --convert-to csv`) | **Validated, adopted** — see §6a. Capture sheet names + convert each sheet to a text/table representation rather than flattening blindly; note the multi-sheet caveat in §6a |
| `png`, `jpg`, `jpeg`, `bmp`, `gif` | `pytesseract` (Tesseract OCR) + `Pillow` for preprocessing (deskew, contrast/threshold adjustment) | OCR quality varies a lot with source image quality — may need a confidence threshold below which a file is flagged for manual review rather than trusted |

### 6a. LibreOffice Validation Test (do this before building legacy `.doc`/`.xls` extraction)

Since LibreOffice is already installed but untested for this purpose, run a quick manual check before implementation commits to it as the legacy-format tool:

1. Grab one real `.doc` and one real `.xls` file from the Documents folder (ideally one from a tax/finance subfolder, since that's the highest-value content).
2. Run:
   ```
   soffice --headless --convert-to txt <sample>.doc
   soffice --headless --convert-to csv <sample>.xls
   ```
3. Check the output for:
   - Did it produce a file at all (some headless LibreOffice invocations fail silently or need `--outdir`)?
   - Is text/table content complete and in a sane order, or garbled/reflowed?
   - For the `.xls` → CSV case: are multiple sheets handled (LibreOffice's CLI convert typically only exports the first sheet — worth confirming), or does it need a per-sheet macro/script instead?
   - Run time per file — if conversion is slow, it affects batch throughput across however many legacy files exist in the corpus.

**Validation results:** `.xls` → CSV worked correctly on the one file tested. `.doc` → txt worked on one file but failed silently on another — produced a file containing only 7 newlines, no actual text (no error, no non-zero exit — it just returned near-empty output). This is a known, accepted failure mode: **decision is to detect and warn, not to fix it.**

**Requirement — empty/near-empty conversion detection:** after any `.doc`/`.xls` LibreOffice conversion, check the resulting text/CSV for meaningful content (e.g., non-whitespace character count below a small threshold, such as <20 characters). If below threshold:
- Mark `status=warning_empty_conversion` in the manifest (new status value, add to §5 schema).
- Log a warning with the file path.
- **Do not attempt any remediation** (no OCR fallback, no alternate tool, no retry) — this is intentionally out of scope. The file is left unindexed and flagged for manual review at your discretion.

LibreOffice headless is adopted as the tool for both `.doc` and `.xls`, given this caveat — no fallback to `antiword`/`catdoc`/`xlrd` is planned unless the empty-conversion rate turns out to be high enough to matter in practice.

### OCR Confidence Threshold (suggestion, since none was specified)

Tesseract (via `pytesseract.image_to_data`) returns a per-word confidence score (0–100). A reasonable starting point:

- **≥70 average confidence** → trust the OCR output, mark `ocr_extracted`.
- **40–69** → still index it, but flag `status=ocr_low_confidence` so it's excluded from automated numeric lookups (like AGI) unless nothing else is found, and surfaced for manual review.
- **<40** → treat as failed OCR, mark `status=failed`, don't index garbage text.

This is a starting point, not a fixed rule — worth tuning after seeing real output on a handful of your scanned files (image quality varies a lot between a phone-scanned tax form and a clean scanner output). Recommend making the thresholds config values rather than hardcoding them, so they can be adjusted without a code change.

## 7. Error Handling & Logging

- One structured log file per run (`logs/ingest_<timestamp>.log`).
- Per-file outcome recorded in both the log and the manifest `status` field.
- End-of-run summary report: counts of `extracted`, `ocr_extracted`, `warning_empty_conversion`, `failed`, `encrypted`, `empty`, `unclassified`, `skipped`, `deleted`.
- Failures on one file must never abort the whole run.

## 8. Idempotency

- Re-running the ingestion script should be safe at any time: only new/changed files (per `content_hash`) get (re-)processed; everything else is a no-op.

## 8a. Concurrency (added for scale — target: 1M documents / 500GB)

Extraction (OCR, PDF parsing, LibreOffice conversion) is CPU-bound and the dominant cost
per file — the original single-threaded implementation processed the real ~2,500-file
corpus in ~22 minutes, almost entirely OCR time. `run_ingest.py` now runs extraction in a
process pool (`config.max_workers`, default `os.cpu_count()`):

- **Workers are pure and stateless.** Each opens its own *read-only* SQLite connection to
  `manifest.db` (safe alongside the single writer under WAL mode — see below) to look up
  a file's prior state, does the expensive extraction work, and returns a result. A
  worker never writes to the database, the filesystem, or the log.
- **The main process is the sole writer.** It consumes worker results as they complete,
  performs the order-dependent Markdown collision-naming (§4b), writes extracted text,
  and upserts the manifest — all logging happens here too, so results are identical to
  the single-threaded implementation regardless of which worker finished a given file.
- **`manifest.db` uses WAL mode** (`PRAGMA journal_mode=WAL`, `synchronous=NORMAL`) and
  **batches commits** (every 200 rows, not one commit per row) — one fsync per row was
  the dominant SQLite bottleneck at large file counts.
- **Every numeric/OCR library is pinned to one thread per worker process**
  (`OMP_NUM_THREADS=1` and equivalents, set in the worker's init hook, before any
  extraction happens). This turned out to matter more than anything else: Tesseract's
  own internal OpenMP thread pool defaults to using every core *per invocation*, so N
  worker processes each also fanning out to N threads causes N² contention. An early
  benchmark of the pool without this fix took 75 minutes on the real corpus — 3.4x
  *slower* than the original single-threaded run despite ~14.7x average core
  utilization, because nearly all of that CPU time was contention, not useful work.
  With single-threaded libraries inside each worker, the same real corpus (2,504 files)
  completed in **214s (3m34s) — a 6.2x speedup** over the 1320s single-threaded baseline
  on this 16-core machine, with byte-for-byte identical output.

## 9. Step 1 Deliverable (handoff boundary)

Output of this step: a script that populates `manifest.db` plus normalized `.txt` files under `extracted_text/` for every successfully processed source file. Step 2 (chunking) consumes this output — it does not touch original source files again.

---

## Open Questions Before Implementation

1. **OCR confidence thresholds** — the §6a suggested values (70 / 40) are a starting point; confirm or adjust after seeing real OCR output on a few scanned files from your corpus, especially the scanned tax PDFs the AGI use case depends on.
2. **`warning_empty_conversion` threshold** — the "<20 non-whitespace characters" trigger in §6a is a reasonable default but untested at scale; worth revisiting once the full `.doc`/`.xls` corpus has run through once, in case the empty-conversion rate is high enough to be worth a follow-up fix later.
