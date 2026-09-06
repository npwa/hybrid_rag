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
ollama pull qwen3:8b             # generation model — confirmed choice, Step 5 (Doc/step-5-requirements.md, Open Q1)
```

Confirmed installed version: `0.32.5`. `qwen3:8b` (5.2GB at Q4_K_M) was chosen for
generation specifically against this machine's 10GB VRAM budget — several larger/MoE
models already pulled here (the `qwen3.6` family, `qwen2.5-coder:32b`) don't fit or lose
their speed advantage under the CPU offload that would require; see the Step 5 doc for
the full reasoning. Now pulled and confirmed working (Step 5 is implemented and tested
end-to-end against it).

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
| `fastapi` | OpenAI-compatible HTTP server for Open WebUI (Step 5 §4). Confirmed installed: `0.141.1`. |
| `uvicorn` | ASGI server to run the FastAPI app. Confirmed installed: `0.52.4`. |
| `mcp` | MCP server for OpenClaw (Step 5 §5) — access point 3 connects over the Model Context Protocol, not the OpenAI-compatible endpoint. Confirmed installed: `2.1.1` (API is `mcp.server.mcpserver.MCPServer`; older `mcp` 1.x used `FastMCP` under a different import path). |

Step 3 (chunking) needs no packages beyond this list — it's pure-Python text processing
plus the standard library (`sqlite3`, `hashlib`, `concurrent.futures`, `re`).

Step 4 (indexing) added only `lancedb` above. The Ollama HTTP client question from the
previous version of this section is resolved: stdlib `urllib.request` turned out to be
sufficient (`indexing/embedder.py`) — no new dependency needed, and the same module is
reused as-is by Step 5's query engine for embedding the query text. FTS5 (the sparse leg)
needs no package at all — it's the stdlib `sqlite3` module (§3 above), used directly via
`ingest/manifest.py`'s FTS5 methods rather than a separate library.

Step 4 has been implemented and verified: 17,693 chunks embedded via Ollama
(`nomic-embed-text`) into both LanceDB and FTS5 in ~2 minutes, 0 failures, idempotent
reruns confirmed, and the delete-cleanup path (chunks marked `deleted` get removed from
both stores, then purged) verified via a synthetic test.

Step 5 (retrieval, fusion, generation, and its three access points) added `fastapi`,
`uvicorn`, and `mcp` above, and has been implemented and verified: real queries against
the real corpus return grounded, cited answers via the CLI (`run_query.py`), the
OpenAI-compatible HTTP endpoint for Open WebUI (`run_server.py`), and the MCP server for
OpenClaw (`run_mcp_server.py`) — all three tested end-to-end, ~6-8s per query. The
generation model correctly declined to guess when an answer wasn't actually in the
retrieved source excerpts, rather than hallucinating one. An opt-in relevance-gated
general-knowledge fallback exists for queries the document collection has nothing on
(off by default — see Doc/step-5-requirements.md §2a).

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

# Step 5 — ask a question (access point 1: CLI)
./run_query.py --config config/query_config.yaml --query "..." --sources

# Step 5 — OpenAI-compatible HTTP server (access point 2: Open WebUI)
./run_server.py --config config/query_config.yaml
# then in Open WebUI: Settings -> Connections -> add http://127.0.0.1:8100/v1 as an
# OpenAI API connection; "hybrid-rag" appears in the model picker.

# Step 5 — MCP server (access point 3: OpenClaw, on npabot-u24)
./run_mcp_server.py --config config/query_config.yaml
# binds to the LAN (0.0.0.0:8200, not 127.0.0.1) since OpenClaw runs on a separate VM;
# add to OpenClaw's config: mcp.servers["hybrid-rag"] = { url: "http://<this desktop's
# LAN IP>:8200/mcp", transport: "streamable-http", enabled: true }
```

The first three are safe to re-run at any time — all are idempotent, only processing
new/changed data (`Doc/step-1-requirements.md` §8, `Doc/step-3-requirements.md` §5,
`Doc/step-4-requirements.md` §4). `run_query.py`/`run_server.py`/`run_mcp_server.py` are
read-only against the indexes — nothing to re-run, just start whichever server you want
running.
