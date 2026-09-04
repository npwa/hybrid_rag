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
   and a chosen LLM model (see Open Questions — not yet confirmed which one).
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

1. **LLM model for answer generation** — not yet confirmed. Several chat/completion
   models are already pulled locally (`qwen2.5:7b-instruct` and others — see
   `Doc/step-4-requirements.md` §2a); which one to use for generation is still open.
2. **HTTP framework** for the §4/§5 server (FastAPI vs. Flask vs. something else) — not
   yet decided.
3. **Port number** for the new HTTP service — needs to avoid `:8080` (Open WebUI) and
   `:11434` (Ollama).
4. **OpenClaw's actual tool/plugin calling convention** — needs investigation.
   §5 proposes reusing the OpenAI-compatible endpoint, but this depends on what OpenClaw
   itself supports for calling out to external tools.
5. **Streaming responses** — starting non-streaming (§4) for simplicity; worth revisiting
   once the basic path works, since streaming is generally expected of a chat UI.
6. **Prompt design** (system prompt wording, how citations are formatted for the model)
   — needs iteration against real queries once implemented; not fully specifiable in
   advance.
7. **Top-K value** (proposed default 8) and RRF's `k` constant (proposed standard value
   60) — reasonable starting defaults, worth tuning empirically once there's a way to
   evaluate answer quality.
