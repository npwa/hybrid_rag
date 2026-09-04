# Step 4 Requirements: Indexing (Dense + Sparse)

Consumes Step 3's `chunks` table and builds the two retrieval indexes from the
architecture diagram — a vector DB (dense leg) and a BM25/keyword index (sparse leg).
This step builds and maintains the indexes only. Query-time retrieval and RRF fusion is
Step 5 (Retrieval + fusion service), and generating an answer from retrieved chunks is
Step 6 (LLM answer generation) — both out of scope here.

---

## 1. Scope & Environment

- **Ollama endpoint — corrected:** `http://localhost:8080` is **Open WebUI**'s frontend
  (confirmed by curl — it returns an HTML page, not a JSON API response), not Ollama
  itself. Ollama's actual API is at the default `http://localhost:11434`, confirmed live
  and responding (`/api/tags` lists 18 pulled models). **Use `:11434` for this step.**
- **Input:** the `chunks` table from Step 3, specifically rows with
  `embedding_status='pending'`.
- Runs on the desktop — the RTX 3080 is available for local embedding inference via
  Ollama.

## 2. Dense leg — embedding + vector DB

### 2a. Embedding model

**Confirmed:** `nomic-embed-text` (768-dim) is already pulled locally
(`nomic-embed-text:latest`, capability `embedding`) — use it. It's a good
general-purpose default and the only embedding-capable model currently pulled; the
17 other local models (qwen2.5/qwen3.6/llama3/mistral/deepseek variants) are all
completion/chat models, not embedding models, and aren't relevant to this step
(some of them — e.g. `qwen2.5:7b-instruct` — will matter later for Step 6, LLM answer
generation, but that's out of scope here).

### 2b. Vector DB

**Recommend LanceDB over Chroma** — revised from an earlier "either works" framing once
the actual target scale (§7: potentially 5–20M chunks, not 10-40K) is accounted for.
Chroma's default index (`hnswlib`) is memory-resident — the whole vector index has to fit
in RAM. LanceDB stores vectors on disk in a memory-mapped columnar format and doesn't
require full in-RAM residency, which matters directly here: see §7 for why a 5–20M-chunk
index can approach or exceed this machine's 62GB RAM under Chroma's model. Neither needs
a separate server process (ruling out Qdrant/Milvus/Weaviate as unnecessary overhead at
single-user scale), so this is specifically about which embedded engine, not
embedded-vs-server.

If the corpus turns out much smaller than the 1M-document target in practice, Chroma's
simplicity is still a fine choice — the recommendation above is scale-driven, not a
strict rule.

Store alongside each vector: `chunk_id`, `file_id`, `rel_path`, `category`, `extension`,
`tags`, `sheet_name`, `ocr_confidence` — everything needed for query-time
filtering/boosting by file type or folder, per the README's stated metadata design goal.

## 3. Sparse leg — BM25

**Confirmed: SQLite FTS5** (`CREATE VIRTUAL TABLE ... USING fts5(...)`, built into
Python's `sqlite3`, has a native `bm25()` ranking function) over `rank_bm25` or another
separate library. Two reasons, both concrete rather than just "simpler":

- **Low-confidence OCR resilience.** `rank_bm25` and most simple keyword-scoring libraries
  build their vocabulary in memory from whatever text they're given, with no real query
  planner behind them — every query is a linear scan over that in-memory structure. FTS5
  is a proper inverted-index implementation with its own on-disk index and query
  optimizer, so noisy/inconsistent tokens from low-confidence OCR text (§3d of
  `step-3-requirements.md`) don't degrade lookup performance the way they would scanning
  a naive in-memory structure — the index itself absorbs vocabulary noise rather than
  the query path having to.
- **Scaling on this hardware.** `rank_bm25` holds its whole corpus in memory with no
  incremental-update story — every rebuild is a full one, which stops being practical
  well before the 5–20M-chunk estimate in §7. FTS5 supports incremental inserts/deletes
  directly against the index and keeps everything in the same `manifest.db` file with
  zero new dependencies, consistent with the WAL-mode/batched-write approach already
  adopted for the `files` and `chunks` tables (Step 1 §8a, Step 3 §8).

Index the same chunk text + `chunk_id` + metadata columns as the dense leg, so both legs
return results keyed by the same `chunk_id` — required for RRF fusion in Step 5.

## 4. Idempotency

- Only chunks with `embedding_status='pending'` get embedded/indexed on a given run; on
  success, flip that row to `embedding_status='embedded'`.
- Chunks marked `embedding_status='deleted'` (set by Step 3 when the source file was
  removed) get removed from both the vector DB and the FTS5 index, not just skipped.
- A chunk whose source content changed: Step 3 already deletes the stale chunk row and
  creates a new one with a new `chunk_id` and `embedding_status='pending'` — this step
  picks it up as a normal new row, no special-casing needed here.

## 5. Error handling & logging

- Ollama call failures (timeout, connection refused, model not found) — log and skip
  that chunk, don't abort the run. It stays `pending` and is retried on the next run.
- Batch embedding calls where possible rather than one Ollama call per chunk in a tight
  serial loop — matters much more at the revised scale estimate (§7: 5-20M chunks) than
  the original 10-40K-chunk estimate this section was written against.
- End-of-run summary: chunks embedded, chunks failed, chunks removed (deleted), FTS5 rows
  added/removed.

## 6. Step 4 Deliverable (handoff boundary)

Output: a populated, queryable vector DB and a populated FTS5 BM25 index, both keyed by
`chunk_id`. No query-time retrieval, no RRF fusion, no LLM call — those are Step 5 and
Step 6 per the README's plan, and out of scope here.

## 7. Scalability (target: 1M documents / 500GB)

Per `step-3-requirements.md` §8, the corpus this is actually being designed for could
produce roughly **5–20 million chunks**, not the "tens of thousands" scale casually
implied elsewhere in this doc. That changes the calculus for both legs:

- **Vector index size.** At 768 dimensions × 4 bytes (float32), raw vector data alone is
  **~15GB at 5M chunks, ~61GB at 20M chunks** — before any index overhead. HNSW-style
  indexes (what both Chroma and LanceDB use for approximate nearest-neighbor search)
  typically add another 1.5–2x on top, so the *low end* of this range already uses over a
  third of this machine's 62GB RAM, and the *high end* exceeds it outright if the index
  must be fully memory-resident. This is the concrete reasoning behind recommending
  LanceDB over Chroma in §2b — LanceDB doesn't require that.
- **FTS5 index build time.** SQLite FTS5 is used in production at far larger scale than
  this, but *building* an index over 5–20M rows of text is a real one-time (or
  incremental) cost — plan for tens of minutes to a couple of hours for a full rebuild,
  not seconds. This doesn't affect query-time latency once built, only how long the
  initial `INSERT INTO ... fts5` batch job takes.
- **Local disk footprint.** Rough total for chunk text + vector index + FTS5 index at
  this scale: on the order of tens of GB, comfortably inside this machine's available
  NVMe space (486GB free as of this writing) — disk is not the constraint here, RAM is.
- **Query-time latency stays fine regardless.** None of the above changes the answer to
  "will retrieval be fast" — ANN search and FTS5 lookups both stay in the tens-of-
  milliseconds range at this scale on modern hardware. The scale concern here is entirely
  about *build-time* resource usage (RAM for the index, wall-clock time to construct it),
  not query-time responsiveness.

---

## Open Questions

1. ~~Confirm the Ollama endpoint~~ — resolved, see §1 (`:11434`).
2. ~~Confirm which embedding model~~ — resolved, see §2a (`nomic-embed-text`).
3. ~~Chroma vs. LanceDB~~ — resolved, see §2b/§7 (LanceDB, driven by the revised scale
   estimate).
4. ~~FTS5 vs. `rank_bm25`~~ — resolved, see §3 (FTS5: better resilience against
   low-confidence-OCR vocabulary noise, and a real incremental-update story at the
   5–20M-chunk scale target, where `rank_bm25`'s full-in-memory-rebuild model breaks
   down).

All four open questions in this step are now resolved.
