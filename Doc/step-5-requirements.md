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
2. **Relevance gate** (`query/relevance.py`): before doing anything else, check whether
   the corpus actually has anything relevant — see §2a. This determines which of the
   remaining steps run.
3. **Query the FTS5 index** with the same query text (BM25-ranked) for the top-N sparse
   results.
4. **Fuse with Reciprocal Rank Fusion**: for each chunk appearing in either ranked list,
   `score = Σ 1 / (k + rank)` across the lists it appears in, using the standard `k = 60`
   constant. Sort by fused score, take the **top-K** (proposed default `K = 8`, tunable —
   see Open Questions).
5. **Build a prompt** from the query + the top-K chunks' text and source metadata (file
   path, so the model can cite where an answer came from).
6. **Generate the answer** by calling Ollama's chat/completion endpoint with the prompt
   and **`qwen3:8b`** (confirmed — see Open Questions #1). The request must explicitly
   set `num_ctx` (proposed `8192`) — Ollama defaults to a 4K context window for any model
   under the 24GiB VRAM tier, which would silently truncate a RAG prompt (query + top-K
   chunks + system prompt) on this machine's 10GB card otherwise.
7. **Return** `{answer, sources: [{rel_path, chunk_id, ...}]}` — never just the bare
   answer text, so every caller (§3–§5) can surface citations if it wants to.

### 2a. Relevance gate & opt-in general-knowledge fallback

**Design decision, confirmed:** by default, this system answers *only* from the
document collection — if nothing relevant is indexed, it says so rather than letting
the underlying LLM (which has its own general knowledge) fill the gap. This matters
specifically because the failure mode of a personal document assistant quietly guessing
a plausible-sounding but fabricated detail (a tax figure, a policy number) is far worse
than it refusing to answer. This is enforced by a system prompt instruction
(`query/generation.py`), not a structural limit — the underlying model can and does
know things the corpus doesn't cover.

An **opt-in** fallback (`allow_general_knowledge_fallback: false` by default,
`config/query_config.yaml`) lets the model answer from its own knowledge when the
corpus has nothing relevant — useful since a personal-document assistant is still more
broadly useful if it can also just answer a stray general question. When triggered, the
answer is always prefixed `"General knowledge (not from your documents):"` — prepended
in code (`generation.label_general_knowledge`), not left to the model to remember to
say, so a document-grounded answer can never be confused with one that isn't.

**Detecting "nothing relevant"** turned out to need real calibration, not a guess: RRF's
fused score (step 4) is rank-based, so it always produces a normal-looking top-K even
when nothing in the corpus is actually relevant — a "best of a bad lot" still ranks
first. The gate instead looks at the *raw* dense-search distances (step 1), before
fusion, since those have an interpretable absolute scale. A single top-1 distance
threshold alone proved unreliable — tested against a real off-topic query ("who was
Mozart"), the single best match landed at a deceptively low distance (0.49, better than
some genuinely relevant queries) purely by coincidence on a short/generic chunk.
An initial pass required **at least 2 of the top dense results** to clear a `0.7`
distance threshold, which correctly separated every query tested at the time:

| query | top-3 distances | hits < 0.7 | verdict |
|---|---|---|---|
| adjusted gross income 2024 | 0.58, 0.60, 0.60 | 3 | relevant |
| who monitors the home alarm system | 0.65, 0.65, 0.79 | 2 | relevant |
| who was wolfgang amadeus mozart | 0.49, 0.91, 0.97 | 1 | not relevant (false lead) |
| how many moons does jupiter have | 0.91, 0.92, 0.93 | 0 | not relevant |

**`min_hits=2` turned out to be wrong** — caught live via the OpenClaw/Signal integration,
which surfaced a real query the CLI hadn't been tested with: "last flew to Palo Alto"
landed a genuine, single-source match (0.57, 0.85, 0.90 — only 1 hit < 0.7) and got
refused, even though `Travel/README` really does answer it. No distance-based rule can
cleanly tell this apart from the Mozart false lead — Mozart's coincidental top-1 (0.49)
is *closer* than Palo Alto's genuine top-1 (0.57). Given that ambiguity, the two failure
modes aren't symmetric: a false negative here refuses a real answer outright, while a
false positive just costs one extra generation call — and generation already declines
correctly when the retrieved excerpts don't substantiate an answer (Mozart still gets "I
don't know" even after passing the gate). So the gate was loosened to **`min_hits=1`**,
keeping it a fast-path optimization for the clearly-nothing-relevant case (Jupiter's
moons: 0 hits) rather than the last line of defense against hallucination — that job
belongs to generation itself.

**`distance_threshold=0.7` was still too tight even with `min_hits=1`** — also caught
live: "Thule Evolution 1800 sold price sale amount" landed its correct, single-source
answer (a terse listing — dimensions, bullet points, a bare `"$400 ... SOLD DONE"`, no
full-sentence prose) at distance 0.72, just over the cutoff, and got refused. Terse/
list-style source documents apparently embed a bit further from a natural-language
question than prose does. Across every real match measured across this project so far
(0.49-0.72, the low end being the Mozart false lead) versus every genuinely-nothing-
relevant case (0.91+), there's a wide, safe gap between 0.72 and 0.91 — so
`relevance_distance_threshold` was raised to **0.85**, comfortably inside that gap.
Confirmed this still correctly rejects Jupiter's-moons-style queries while fixing both
the Palo Alto and Thule false negatives.

Both threshold values (`relevance_distance_threshold: 0.85`, `relevance_min_hits: 1`) are
config, not hardcoded — like the OCR confidence thresholds in Step 1, this is a starting
point calibrated against real queries, not a fixed rule, and may need retuning as the
corpus grows. Both revisions above were caught only once real, unpredictable questions
came in via the OpenClaw/Signal integration — the CLI testing alone hadn't exercised
either edge case.

When the gate says "not relevant" and the fallback is off (default), the query never
reaches the LLM at all — confirmed in testing to return in ~1.3s vs. ~6s for a real
generation call, since there's nothing to ground an answer in.

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

**Resolved — different from the original proposal.** OpenClaw does not call arbitrary
HTTP APIs or the OpenAI chat-completions shape directly; it connects to external tools
over the **Model Context Protocol (MCP)**, configured under `mcp.servers` in OpenClaw's
own config (JSON5), e.g.:

```json5
mcp: {
  servers: {
    "hybrid-rag": {
      url: "http://192.168.1.53:8200/mcp",
      transport: "streamable-http",
      enabled: true,
    },
  },
}
```

(`192.168.1.53` is this desktop's LAN IP as of this writing — confirm it hasn't changed
if this stops working, e.g. `hostname -I`.)

**Implemented** (`query/mcp_server.py`, `run_mcp_server.py`): the official `mcp` package
(PyPI) provides `MCPServer` (note: `FastMCP` in `mcp` 1.x, renamed in 2.x — this project
pins to whatever `pip install mcp` resolves to, currently 2.x) for exposing a function as
a tool with minimal boilerplate. Wraps the *same* `query.engine.answer_query()` used by
the CLI and Open WebUI as a single tool, `ask_documents(query: str)` — all three access
points share one implementation, this is just a third thin adapter around it.

**Network reachability — resolved.** Confirmed: `npabot-u24` can already initiate
connections to this desktop directly, no tunnel needed in that direction (the existing
tunnel is only for the *other* direction — reaching OpenClaw's own localhost-only web UI
from this desktop). So the MCP server binds to `0.0.0.0` (`mcp_host` in
`config/query_config.yaml`, default changed from the HTTP server's `127.0.0.1`) rather
than needing a tunnel — reachable at the desktop's LAN IP on port `8200`.

**Verified working end-to-end** using the official `mcp` Python client (not just an HTTP
port check): session initialize, `list_tools()` correctly returns `ask_documents` with
its docstring as the description, and `call_tool()` returns the same grounded, cited
JSON answer as the other two access points — for the AGI question, identical result to
the CLI and Open WebUI tests. Also confirmed reachable via the actual LAN IP
(`192.168.1.53:8200`), not just loopback, matching how `npabot-u24` will connect.

**Real Signal round-trip — now confirmed working end-to-end**, after three separate
issues surfaced only once actually wired to a live agent (none of them visible from the
protocol-level `mcp` client test above):

- **Permissions.** OpenClaw needs the tool in *two* places, not one:
  top-level `tools.allow` (the agent's allowlist) **and** a separate
  `tools.sandbox.tools.alsoAllow` gate — distinct from `agents.defaults.sandbox`, which
  only configures sandbox mode/docker settings — required whenever
  `agents.defaults.sandbox.mode` is `"non-main"`. Missing the second one silently drops
  the tool with no error visible to the end user.

- **Model tool-calling reliability.** This is a separate model choice from
  `generation_model` above — that one runs *inside* this project doing grounded RAG
  generation; this one is OpenClaw's own agent model (`agents.defaults.model.primary`),
  deciding *whether* to call `ask_documents` at all. Every 8-14B model tried
  (`mistral:latest`, `qwen2.5:14b-instruct`, `llama3.1:8b`) failed in production despite
  being Ollama-tagged `tools`-capable, in three different ways: declining outright,
  dumping the tool-call JSON as plain text instead of Ollama's structured `tool_calls`
  field (OpenClaw detects this exact pattern — logged as `"Assistant reply looks like a
  tool call, but no structured tool invocation was emitted"` — but doesn't recover it
  into a real call), or answering a stale/unrelated question entirely. This reproduced
  even in isolated `curl` tests against Ollama directly (bypassing OpenClaw), confirming
  it's a model-capability ceiling, not an OpenClaw or config bug — consistent with
  OpenClaw's own docs, which say models under ~14B "often struggle with complex
  multi-step tool calling" and recommend 30B+. `qwen3.6:35b-a3b` (already pulled, MoE —
  runs beyond the 10GB VRAM budget by spilling to CPU/RAM, slower but survives it since
  only ~3B params are active per token) passed every test, including under a realistic
  multi-tool system prompt, and is now the configured default.

- **Privacy-refusal framing.** Separately from capability, `qwen3.6:35b-a3b` initially
  *declined* a real test question ("United Mileage plus account number?") outright,
  treating it as sensitive personal data it shouldn't access — not a tool-selection
  failure, a safety-alignment reflex. Fixed by adding explicit reassurance to both the
  MCP server's `instructions` and the `ask_documents` tool docstring
  (`query/mcp_server.py`): looking up a specific personal fact this way is the *intended*
  use of the tool, not a privacy violation, since the user explicitly indexed and
  consented to this collection being searched on their behalf. Confirmed this doesn't
  cause over-triggering on unrelated general-knowledge questions.

- **The privacy-refusal root cause was actually in OpenClaw's own workspace files, not
  ours.** `~/.openclaw/workspace/SOUL.md` has a line — *"Private things stay private.
  Period."* — clearly meant to mean "don't leak the user's data to others," but generic
  enough that a model could read it as "don't retrieve the user's own data for them."
  Confirmed by testing the real, unedited SOUL.md/AGENTS.md/USER.md content (not a
  hand-written approximation) directly against Ollama: it reproduced the exact refusal.
  Fixed at the source — clarified the boundary in SOUL.md, plus a direct
  `hybrid-rag__ask_documents`-specific note added to AGENTS.md's "local notes" cheat
  sheet — since the `mcp_server.py` framing alone wasn't enough once diluted by the rest
  of a real, longer system prompt. This lesson generalizes: **when a local model
  misbehaves with an OpenClaw tool, check OpenClaw's own workspace files
  (`SOUL.md`/`AGENTS.md`/`MEMORY.md`/`USER.md`) for a competing or ambiguous instruction
  before assuming the tool's own description needs more work.**

### 5a. The `qwen3:8b` speed experiment (attempted, reverted)

`qwen3.6:35b-a3b` fixed every failure mode above, but at a real cost: ~14s average
response time, since it doesn't fit the 10GB VRAM budget (65%/35% CPU/GPU split). Given
`qwen3:8b` is already this project's own `generation_model` (§2), runs 100% GPU-resident,
and is ~6x faster, it was worth testing as OpenClaw's *agent* model too — a different
role than `generation_model` (that one does grounded RAG generation *inside* this
project; this one is OpenClaw's own model deciding *whether* to call `ask_documents` at
all).

**Built `scripts/eval_tool_calling_models.py`** to make this repeatable: it extracts the
live `ask_documents` docstring directly from `query/mcp_server.py` (so it can't drift out
of sync with production) and replays every real failure mode found so far against any
candidate model via direct Ollama `/api/chat` calls — bypassing OpenClaw entirely, which
is both this script's strength (isolates the model as a variable) and, as this section
documents, its limit (it can't see what OpenClaw's own runtime actually sends).

Initial results looked like a clean win: `qwen3:8b` passed every scripted case,
including 9/9 repeats of the original three, once a *system-prompt-level* reassurance was
added (the `mcp_server.py`-only fix wasn't enough for this particular model — needed the
same "not a privacy concern" framing one level up, in the system prompt itself). It also
correctly discriminated `web_search` (weather) from `ask_documents` (personal facts) from
answering directly (general trivia).

**It still failed live, repeatedly, in ways the test script never caught:**

1. First live symptom: re-asking the *exact same* question later in the same
   conversation skipped the tool and answered from its own memory of the earlier turn.
   Reproduced this in isolation and fixed it with explicit "call it fresh every time,
   even for an identical repeat" language in both SOUL.md and AGENTS.md — validated 5/5,
   no regressions.
2. Still failed live after that deploy. Investigated whether OpenClaw's config even
   assembles `SOUL.md + AGENTS.md + USER.md` into one system prompt the way the eval
   script assumes — confirmed the live workspace also has `MEMORY.md`, `IDENTITY.md`, and
   `SESSION.md`, none of which the eval script accounts for. `MEMORY.md` in particular
   carries its own forceful, competing directive ("BEFORE answering any question about
   past conversations... you MUST call `memory_search`... the workspace folder is the
   source of truth") — plausible cause, but reproducing it locally (concatenating
   `MEMORY.md` into the test prompt) still passed 5/5, so this alone wasn't it either.
3. Found a real, confirmable variable instead: Ollama's `think` field for Qwen3 models.
   `think: false` and `think: true` were both reliable (3/3) in isolation; `think` *left
   unset* (Ollama/OpenClaw's actual default when a caller doesn't know about this
   Qwen3-specific field) was flaky — 2 of 3 runs answered from memory despite the model's
   own reasoning trace correctly noting "the user is asking again... let me check the
   previous interaction." Confirmed via OpenClaw's docs that a per-model
   `agents.defaults.models."<model>".params.thinking` override exists. Set it to `false`
   to match this project's own generation-model choice (§2, "faithfulness over
   chain-of-thought") — but this made things *worse*, not better, live: the model began
   fixating on the most recently established fact even for entirely unrelated follow-up
   questions, and fabricated a plausible-looking but made-up answer for one genuinely new
   question (Delta frequent-flier number) instead of calling the tool or declining.
   Switching to `thinking: true` fixed the exact 4-message adversarial sequence that
   exposed this (repeat → two garbled queries → one real new question) — all 4 handled
   correctly, including the garbled ones (erring toward checking rather than fabricating).
4. **Still failed live even with `thinking: true`**, specifically back on the *original*
   literal-repeat case — reliably using memory for a repeated topic while correctly using
   the tool for genuinely new ones. Re-tested the literal repeat 10/10 in isolation with
   `thinking: true` and it passed every time — a full, direct contradiction of live
   behavior.

**Conclusion: reverted to `qwen3.6:35b-a3b`, this time with `num_ctx: 8192` capped
(keeps it mostly GPU-resident, faster than the untested full-32K default) — validated 5/5
on the literal repeat and 4/4 on the full adversarial sequence, matching its clean record
across every other real Signal message sent so far.** The `qwen3:8b` experiment is not
resumed. Each isolated fix passed every test thrown at it, then failed live in a new way
— a pattern that points at a real capacity/robustness gap for an 8B model under
OpenClaw's actual runtime conditions (likely its memory system injecting recalled facts
through some channel other than plain conversation-history text, which `curl`-testing
against raw Ollama cannot see or reproduce), not a prompt or config problem with a next
fix waiting to be found. **Do not re-attempt switching OpenClaw's agent model to
something smaller than `qwen3.6:35b-a3b` without first finding a way to observe
OpenClaw's actual constructed request to Ollama** (not just the final reply) — every
attempt so far to reason about this from the outside, via config docs and isolated
replication, has produced a fix that worked in testing and failed live.

### 5b. MEMORY.md: another competing directive in OpenClaw's own workspace

Even after reverting to `qwen3.6:35b-a3b`, a real Signal message ("Seriously, when did I
last fly to Palo Alto?" — a question asked across several earlier days per this
project's own query logs) still skipped `ask_documents` entirely and called
`memory_search` instead, with no `QUERY` log entry on this project's side at all. Same
root-cause class as the SOUL.md finding in §5 above: `~/.openclaw/workspace/MEMORY.md`
carries its own explicit, forceful directive —

> "BEFORE answering any question about past conversations... you MUST call
> `memory_search`... the workspace folder is the source of truth."

— and a question phrased around "last..."/referencing something asked before is
reasonably read by the model as "a question about a past conversation," triggering this
rule ahead of anything in SOUL.md/AGENTS.md. Reproduced directly (4/5 calls went to
`memory_search` instead of `ask_documents` using the real, unedited `MEMORY.md` content).
Fixed with a single added line under MEMORY.md's "RAG Directives," an explicit carve-out:
personal-document questions (account numbers, dates, purchases, travel, medical records,
etc.) always go through `ask_documents`, never `memory_search`, regardless of whether the
topic came up before — `memory_search` is reserved for questions about the assistant's
own conversational history, not for facts the document collection holds. Validated 6/6
on the failing case, confirmed `memory_search` still correctly fires for a genuine
meta-conversation question ("What did we decide about the database schema last week?"),
and no regressions on the original three cases.

**This generalizes the §5 lesson further: OpenClaw's workspace can carry an arbitrary
number of files (`SOUL.md`, `AGENTS.md`, `MEMORY.md`, `IDENTITY.md`, `SESSION.md` were
all found present on this deployment), any of which can define a directive that competes
with or pre-empts a tool's own description.** Each one found in this project so far
(`SOUL.md`'s privacy-refusal line, `MEMORY.md`'s memory_search mandate) was worded
correctly for its own original intent and only became a problem in combination with a
new tool being added later — there is no reason to assume these are the last two. Any
future "the model isn't calling the tool" report should start by grepping the full live
workspace for related keywords (`memory`, `private`, `personal`, the tool's own name),
not by re-tuning `query/mcp_server.py`'s description again.

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
4. ~~OpenClaw's actual tool/plugin calling convention~~ — **resolved: MCP**
   (Model Context Protocol), not the OpenAI-compatible endpoint originally proposed —
   see §5. Remaining sub-question: how the MCP server (desktop) becomes reachable from
   OpenClaw (separate VM) — a decision for the user, not yet made.
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
