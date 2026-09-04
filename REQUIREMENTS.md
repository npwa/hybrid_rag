# Requirements

What has to be installed on a machine for this project to run, and how to install it.
This is a living document — it currently covers Steps 1–3 (ingestion, extraction,
chunking), which are implemented and verified, plus what's already confirmed for Step 4
(indexing). It will be revised as later steps (5–8, per the README's high-level plan) are
implemented. If a step turns out to need something not listed here, add it here as part
of that step's work — this file should never fall behind what the code actually needs.

Everything below has been verified against the actual machine this project was built and
tested on (Ubuntu 24.04.4 LTS), not assumed. Package names and versions are what's
confirmed installed there. It has not been tested on macOS or Windows — the ingestion
pipeline in particular relies on Linux-specific process-pool behavior (`fork` start
method; see `Doc/step-1-requirements.md` §8a) and is written and tested for Linux only.

---

## 1. Target platform

- **OS:** A mainstream Linux distribution with `apt`. Built and tested on **Ubuntu 24.04
  LTS**; should work unmodified on other recent Ubuntu/Debian releases. Not tested on
  RHEL/Fedora/Arch — package names would need translating (e.g. `dnf`/`pacman`
  equivalents of the `apt` packages below), but nothing in the code is Ubuntu-specific.
- **Python:** 3.10+ (built and tested on 3.12.3). The codebase uses modern union-type
  annotations (`str | None`) throughout.

## 2. Hardware

Nothing here is a hard minimum enforced by the code — these are what this project was
actually developed and load-tested against, given as a practical baseline.

| Resource | Used for development | Notes |
|---|---|---|
| CPU | 16 cores | Ingestion (Step 1/2) and chunking (Step 3) both run a process pool sized to `os.cpu_count()` by default — more cores means proportionally faster runs on a large corpus. A single-core machine still works, just serially. |
| RAM | 64GB | Comfortable for corpora up to the low millions of chunks. See `Doc/step-4-requirements.md` §7 for why RAM matters specifically for the *vector index* at large scale, and why LanceDB (disk-backed) rather than Chroma (memory-resident) was chosen partly to avoid a hard RAM requirement growing with corpus size. |
| Disk | NVMe SSD, 500GB free | Not a hard requirement — a regular SSD or HDD works, just slower for the OCR/LibreOffice-heavy extraction pass and for building the FTS5 index at scale (`Doc/step-3-requirements.md` §8). |
| GPU | NVIDIA RTX 3080, 10GB VRAM | Used by Ollama to accelerate embedding generation (Step 4) and, later, LLM inference (Step 6). **Recommended** — Ollama runs on CPU too, just slower. No GPU-specific code exists in this repo; the GPU is entirely Ollama's concern, invoked over its HTTP API. |

## 3. System (OS-level) packages

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-eng \
    libreoffice-writer libreoffice-calc \
    git
```

| Package | Why | Confirmed version |
|---|---|---|
| `python3`, `python3-venv`, `python3-pip` | Runtime + virtual environment + package installer. On Debian/Ubuntu these are separate packages from the `python3` interpreter itself. | 3.12.3 |
| `tesseract-ocr` (+ `tesseract-ocr-eng`) | OCR for scanned PDFs and images (`ingest/extractors/pdf.py`, `image.py`), invoked via the `pytesseract` Python wrapper, which shells out to the `tesseract` binary. | 5.3.4 |
| `libreoffice-writer`, `libreoffice-calc` | Legacy `.doc`/`.xls` conversion via headless `soffice` (`ingest/extractors/office.py`). Only these two components are needed — not the full `libreoffice` meta-package (no Impress/Draw/Base use here). | 24.2.7.2 |
| `git` | Version control (this repo). | — |

**Additional Tesseract language packs**: only `tesseract-ocr-eng` is installed/needed on
the development machine, since the source corpus is English-only. For a non-English
corpus, install the relevant `tesseract-ocr-<lang>` package(s) and set `tesseract_lang` in
`config/ingest_config.yaml` accordingly (see `pytesseract`/Tesseract docs for language
codes).

**SQLite FTS5**: not a separate package — it needs to be *compiled into* the Python
`sqlite3` module, which it is on stock Ubuntu 24.04's Python 3.12. Verify on any other
system before relying on it (Step 4's sparse leg depends on this):

```bash
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print('FTS5 OK')"
```

If that fails, the fix is a Python built against a SQLite with FTS5 enabled (rebuilding
Python, or using a distro Python package that already has it — this has not come up on
Ubuntu 24.04 but is worth checking on other distros/Python builds).

## 4. Ollama (external service)

Not a Python package — a separate service this project talks to over HTTP. Confirmed
running at `http://localhost:11434` (Ollama's default port; **not** `:8080`, which is
Open WebUI's frontend if that's also installed — see `Doc/step-4-requirements.md` §1 for
how that distinction was discovered).

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text     # embedding model — confirmed choice, Step 4 §2a
```

Confirmed installed version: `0.32.5`. A chat/completion model (for Step 6, LLM answer
generation — not yet implemented) will be added to this section when that step is built;
`qwen2.5:7b-instruct` and several others are already pulled on the development machine as
candidates, but none is confirmed as *the* choice yet.

## 5. Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Currently required (Steps 1–3 — implemented and in `requirements.txt`)

| Package | Used for |
|---|---|
| `PyMuPDF` | PDF text extraction, page rendering for OCR fallback |
| `python-docx` | `.docx` text extraction |
| `pytesseract` | Python wrapper around the `tesseract` binary (OCR) |
| `pikepdf` | PDF encryption detection |
| `msoffcrypto-tool` | Encryption detection for legacy Office formats (`.doc`/`.xls`) and `.docx`/`.xlsx` |
| `openpyxl` | `.xlsx` reading (table-aware extraction) |
| `Pillow` | Image preprocessing before OCR |
| `PyYAML` | Config file loading (`ingest_config.yaml`, `chunk_config.yaml`) |
| `charset-normalizer` | Encoding detection for plain-text files that aren't UTF-8 |
| `lancedb` | Dense-leg vector store (Step 4 §2b) — embedded, disk-backed, no server process. Confirmed installed: `0.38.0`. |

Step 3 (chunking) needs no packages beyond this list — it's pure-Python text processing
plus the standard library (`sqlite3`, `hashlib`, `concurrent.futures`, `re`).

Step 4 (indexing) added only `lancedb` above. The Ollama HTTP client question from the
previous version of this section is resolved: stdlib `urllib.request` turned out to be
sufficient (`indexing/embedder.py`) — no new dependency needed. FTS5 (the sparse leg)
needs no package at all — it's the stdlib `sqlite3` module (§3 above), used directly via
`ingest/manifest.py`'s FTS5 methods rather than a separate library.

Step 4 has been implemented and verified: 17,693 chunks embedded via Ollama
(`nomic-embed-text`) into both LanceDB and FTS5 in ~2 minutes, 0 failures, idempotent
reruns confirmed, and the delete-cleanup path (chunks marked `deleted` get removed from
both stores, then purged) verified via a synthetic test.

## 6. Configuration

Both `ingest_config.yaml` and `chunk_config.yaml` live in `config/`.
`ingest_config.yaml` is git-ignored (it embeds a personal filesystem path,
`source_root`) — copy the tracked example and edit it:

```bash
cp config/ingest_config.example.yaml config/ingest_config.yaml
# edit config/ingest_config.yaml: set source_root to your own document tree
```

`chunk_config.yaml` and `index_config.yaml` have no personal paths and are tracked
directly — usable as-is.

## 7. Running the pipeline

```bash
source .venv/bin/activate
./run_ingest.py --config config/ingest_config.yaml     # Step 1/2: discover, classify, extract
./run_chunk.py  --config config/chunk_config.yaml       # Step 3: split into retrieval chunks
./run_index.py  --config config/index_config.yaml       # Step 4: embed + index (dense + sparse)
```

All three are safe to re-run at any time — all are idempotent, only processing
new/changed data (`Doc/step-1-requirements.md` §8, `Doc/step-3-requirements.md` §5,
`Doc/step-4-requirements.md` §4). Step 5's entrypoint (`run_query.py` — retrieval,
fusion, and answer generation) will be added here once it exists.
