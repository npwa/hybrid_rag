# Step 5 Requirements: Retrieval, Fusion, Answer Generation & Interfaces

Consumes Step 4's dense (LanceDB) and sparse (SQLite FTS5) indexes and turns a natural-
language query into a generated answer, exposed through three different access points.

**Scope note:** this consolidates README plan items **5** (Retrieval + fusion service),
**6** (LLM answer generation), and **7** (Interface wiring) into one implementation step
— the same way `step-1-requirements.md` combined plan items 1 and 2. The reason: "three
ways to access the system" only makes sense once the full query→answer path exists, not
retrieval alone, so splitting 5/6/7 into separate implementation passes would mean
building and testing each interface against a moving target. Step 8 (maintenance loop —
incremental re-indexing) is **not** covered here and remains a separate future step.

This document will be revised as implementation gets closer — several things below
(model choice, port numbers, OpenClaw's actual integration surface) are flagged as open
rather than settled.

---

## 1. Scope & Environment

- **Input:** Step 4's LanceDB vector index and SQLite FTS5 index, both keyed by
  `chunk_id`, both carrying the same metadata (`rel_path`, `category`, `tags`,
  `sheet_name`, `ocr_confidence`, ...).
- **Output:** for a given query — a generated answer, plus the source chunks it was
  grounded in (for traceability/citation back to the original files, per the README's
  stated metadata design goal).
- Runs on the same desktop as everything else in this project — Ollama, LanceDB, and
  FTS5 are all already local; no new external services are introduced.
- The core retrieval/fusion/generation logic is a single **interface-agnostic** Python
  component (§2). Everything else in this doc (§3–§5) is a thin adapter around it — this
  is what makes "three ways to access" cheap: each interface is a different caller of the
  same function, not a separate reimplementation.

## 2. Core query engine (interface-agnostic)

Given a query string, in order:

1. **Embed the query** via Ollama's `nomic-embed-text` (same model as Step 4's indexing,
   for a query/document embedding-space match) and search the LanceDB index for the
   top-N dense results.
2. **Query the FTS5 index** with the same query text (BM25-ranked) for the top-N sparse
   results.
3. **Fuse with Reciprocal Rank Fusion**: for each chunk appearing in either ranked list,
   `score = Σ 1 / (k + rank)` across the lists it appears in, using the standard `k = 60`
   constant. Sort by fused score, take the **top-K** (proposed default `K = 8`, tunable —
   see Open Questions).
4. **Build a prompt** from the query + the top-K chunks' text and source metadata (file
   path, so the model can cite where an answer came from).
5. **Generate the answer** by calling Ollama's chat/completion endpoint with the prompt
   and **`qwen3:8b`** (confirmed — see Open Questions #1). The request must explicitly
   set `num_ctx` (proposed `8192`) — Ollama defaults to a 4K context window for any model
   under the 24GiB VRAM tier, which would silently truncate a RAG prompt (query + top-K
   chunks + system prompt) on this machine's 10GB card otherwise.
6. **Return** `{answer, sources: [{rel_path, chunk_id, ...}]}` — never just the bare
   answer text, so every caller (§3–§5) can surface citations if it wants to.

This engine takes zero dependency on how it's invoked — no HTTP, no CLI parsing, no
Signal-specific code lives here. It should be usable as a plain importable Python
function/class from a test script, the CLI (§3), or the HTTP server (§4/§5).

## 3. Access point 1 — CLI

`run_query.py --query "..."` — a thin wrapper that calls the core engine in-process and
prints the answer (and, with a flag, the retrieved source chunks) to stdout.

Purpose: local testing and debugging without needing Open WebUI or OpenClaw/Signal wired
up — useful from the moment §2 exists, well before §4/§5 are built.

## 4. Access point 2 — Open WebUI

Open WebUI (already running on this machine, `:8080`) can add any OpenAI-API-compatible
backend as a custom model under Settings → Connections. This is **not** Open WebUI's own
built-in document RAG (which would bypass everything built in Steps 1–4) — it's Open
WebUI acting purely as a chat frontend for *this* project's backend.

Requires a small local HTTP server exposing:

- `POST /v1/chat/completions` — OpenAI chat-completion request/response shape. Take the
  latest user message as the query, run the core engine (§2), return the answer as the
  assistant message. Non-streaming (single blocking response) for v1 — see Open
  Questions.
- `GET /v1/models` — lists one synthetic model id (e.g. `hybrid-rag`) so it shows up in
  Open WebUI's model picker.

Runs on its own local port — **not** `:8080` (Open WebUI itself) or `:11434` (Ollama);
exact port TBD (Open Questions).

## 5. Access point 3 — OpenClaw / Signal

Per the original plan: OpenClaw (on a separate VM, wired to Signal via `signal-cli`)
calls this system as a tool when a Signal message arrives, and relays the answer back as
a Signal reply.

**Proposed:** OpenClaw calls the *same* `/v1/chat/completions` endpoint from §4, rather
than a bespoke third integration — if OpenClaw can call arbitrary HTTP APIs as a tool,
one endpoint serves both Open WebUI and OpenClaw with no extra code. This needs
confirming against OpenClaw's actual tool/plugin interface before it's locked in (Open
Questions) — it may turn out OpenClaw expects a different calling convention.

## 6. Error handling & logging

- Retrieval failure (LanceDB/FTS5 unreachable or errors), embedding failure (Ollama
  unreachable), generation failure (LLM call errors or times out) — each degrades to a
  clear error response, never a crash. Since this is a long-running service rather than a
  batch job, the invariant from Steps 1–3 ("one bad file never aborts the run") becomes
  "one bad request never crashes the service" — the process keeps serving subsequent
  queries regardless of what happened on a prior one.
- Structured per-query logging (timestamp, query text, retrieved `chunk_id`s, fused
  ranking, generation latency) to `logs/query_<date>.log` — one growing log per day
  rather than one per run, since this is a long-running service, not a batch script like
  Steps 1–3.

## 7. Step 5 Deliverable (handoff boundary)

Output: one interface-agnostic query engine (§2) plus three working ways to call it — a
CLI script, an OpenAI-compatible HTTP endpoint Open WebUI can use directly, and that same
endpoint wired into OpenClaw for Signal. Step 8 (incrementally detecting and re-indexing
new/changed files) is separate and not covered here.

---

## Open Questions

1. ~~LLM model for answer generation~~ — **confirmed: `qwen3:8b`** (needs `ollama pull
   qwen3:8b`, not yet pulled — 5.2GB at Q4_K_M). Researched against the actual GPU
   budget (RTX 3080, 10GB VRAM) rather than just picking from what's already pulled:
   - Several already-pulled models were ruled out for this specific role. The `qwen3.6`
     family (35B-A3B and variants, 24GB) and `qwen2.5-coder:32b` (20GB) are MoE/large
     models that don't fit in 10GB VRAM — and critically, MoE's whole point (cheap
     per-token compute despite a large total size) only holds when it's GPU-resident;
     forced onto CPU offload at this VRAM budget, that advantage disappears and it would
     likely run *slower* than a properly-sized dense model despite scoring higher on
     benchmarks. `qwen2.5:14b-instruct` (9GB) technically fits on paper but leaves too
     little headroom for KV cache + CUDA overhead on a 10GB card to trust.
   - `qwen3:8b` is a genuine generational upgrade over the already-pulled
     `qwen2.5:7b-instruct` while staying dense (no offload tradeoff), fits with ~3.8GB of
     headroom to spare, has a native 32K context window (see §2 step 5's `num_ctx` note),
     and supports an optional "thinking" mode — left off by default for RAG (faithfulness
     to retrieved context matters more than chain-of-thought for grounded QA), available
     to toggle on for genuinely multi-hop questions later if needed.
   - Fallback if pulling something new isn't wanted: `qwen2.5:7b-instruct`, already
     pulled, comparable quality, smallest footprint (4.68GB) of the viable candidates.
2. ~~HTTP framework~~ — **confirmed: FastAPI** (+ `uvicorn`). Good fit for an
   OpenAI-compatible shim: automatic request validation via Pydantic, minimal
   boilerplate for the `/v1/chat/completions` + `/v1/models` shape.
3. ~~Port number~~ — **confirmed: `8100`** (checked free on this machine at
   implementation time; avoids `:8080` Open WebUI and `:11434` Ollama).
4. **OpenClaw's actual tool/plugin calling convention** — still needs investigation.
   §5 proposes reusing the OpenAI-compatible endpoint, but this depends on what OpenClaw
   itself supports for calling out to external tools. Not blocking — the endpoint exists
   and works regardless of how OpenClaw ends up calling it.
5. **Streaming responses** — implemented non-streaming (§4) for v1; confirmed working
   end-to-end (CLI and HTTP both tested against the real corpus, ~6-8s per query
   end-to-end including generation). Worth revisiting later since streaming is generally
   expected of a chat UI, but not required for a working v1.
6. **Prompt design** — a first version is implemented (`query/generation.py`): cite
   sources by `[N]` marker, explicit instruction to say "I don't know" rather than guess
   when the answer isn't in the retrieved excerpts. Verified working as intended in
   testing — a query with no clear answer in the source documents correctly produced "the
   specific insurance company is not named in the sources" rather than a hallucinated
   answer. Still worth iterating on with more real queries.
7. **Top-K value** (8) and RRF's `k` constant (60) — implemented as the defaults
   proposed. Real testing shows retrieval sometimes pulls in tangentially-related
   documents (e.g. large financial PDFs matching on generic terms) alongside the
   genuinely relevant ones; the LLM correctly ignored the noise in testing so far, but
   this is the first real tuning candidate if answer quality issues show up — narrowing
   `top_n_dense`/`top_n_sparse` or `top_k_fused` would be the first thing to try.
