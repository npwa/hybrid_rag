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

**Fusion diagnostics.** Each source in the returned list also carries `branch` (`dense`,
`sparse`, or `dense+sparse` — which leg(s) actually found it), `rrf_score`, and the raw
per-leg rank/score (`dense_rank`/`dense_distance`, `sparse_rank`/`sparse_bm25`; `None`
for a leg that didn't return the chunk at all). Added because the fused list alone
doesn't say *why* a source was picked — a source that both legs agree on and one that
survived only because it was rank 1 in an otherwise-empty leg look identical without
this. `query/fusion.py::rrf_fuse` computes it (merging per-leg metadata rather than the
original first-list-wins `meta.setdefault`, so both legs' raw scores survive when a
chunk appears in both), and both the query log (`fusion detail:` line, at INFO — visible
in `logs/query_<date>.log` without any config change) and `./run_query.py --scores`
(a formatted table) surface it. `--sources` alone still shows only file paths, unchanged.

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

### 5c. `qwen3:8b`, attempt two — same failure, resource-starvation risk forces the question anyway

Weeks after §5a's revert, real operation of `qwen3.6:35b-a3b` surfaced costs well beyond
latency: a genuine OOM event (two browser processes kernel-killed; swap fully exhausted,
<1.2GB RAM available) correlated with its ~15GB+ CPU-resident footprint, and separately, a
confirmed, repeatable pattern of `hybrid-rag__ask_documents` calls failing outright —
`MCP error -32001: Request timed out`, exactly 60.0s after `tool_execution_started`,
across multiple different questions. Direct testing proved our own MCP server answers in
~6.6s when Ollama is otherwise idle; the timeouts only occurred while `qwen3.6:35b-a3b`'s
own CPU-bound generation was also active on the same shared Ollama instance — i.e. the
large model wasn't just slow, it was starving a *different* part of the system of the
CPU it needed, with no interaction between the two beyond sharing hardware.

That raised a real question the first attempt never tested: were any of §5a's "passes
isolated, fails live" mysteries actually a **concurrency** artifact — two simultaneous
callers (OpenClaw's own reasoning and our tool's generation) hitting the same model at
once, something no sequential `curl` test had ever exercised? Tested directly: 6 trials,
each firing both sides genuinely concurrently via threads. Result: 6/6 clean, steady
~108-119 tok/s on both sides regardless of overlap, zero interference. **Concurrency was
not the hidden cause.**

Given that result plus the now-concrete resource-starvation cost of staying on the large
model, a second real attempt at `qwen3:8b` was made — this time with the §5a and §5b
fixes already in place and confirmed live on the real workspace (verified by reading back
`SOUL.md`/`AGENTS.md`/`MEMORY.md` from `npabot-u24` directly before switching, not
assumed). First test (a fresh question) succeeded cleanly: tool called, answer verified
correct against the source PDFs down to specific dates, 12s round trip, no resource
issue. **Second test — the exact literal-repeat case, the original failure — failed
again**, immediately: no `tools/call`, no log entry on either side, confirmed by checking
both the correctly-dated log file and (after discovering and fixing an unrelated logging
bug — see below) the one it had been misfiled under. Same failure, same model, two
independent attempts weeks apart, with every known fix in place and concurrency now ruled
out as a confound.

**Reverted to `qwen3.6:35b-a3b` a second time. At the time this was written, this was a
closed question, not an open one**: `qwen3:8b` is not viable as OpenClaw's agent model,
full stop, regardless of future workspace-file or config fixes, unless OpenClaw's actual
constructed request to Ollama becomes observable (not available at the time). **§5f
below found exactly that observability** — this conclusion should be re-tested with that
tool before being treated as final. The real, now-confirmed costs of staying
on `qwen3.6:35b-a3b` (OOM risk, contention-driven tool-call timeouts) need to be addressed
on their own terms — `OLLAMA_KEEP_ALIVE` (identified back in §5a's era, still never
applied) is the most direct lever, since it bounds how long the ~15GB+ CPU-resident
footprint lingers after each use.

**Side finding, worth its own fix regardless of the model question**: `query/logging_setup.py`'s
daily log file path was computed once, when a long-running process starts — correct for
the CLI (one process per invocation) but wrong for `run_mcp_server.py`/`run_server.py`,
which have run continuously for weeks without restarting. Every query for a month was
silently filed under the server's *startup* date, never rotating, discovered when a real,
verified-correct Signal answer appeared to have "never called the tool" simply because
the log was being checked under the right day's filename. Fixed with a handler that
re-checks the date on every write, not just at startup.

### 5d. The §5c revert command was never actually applied — a third failure mode found by accident

The `openclaw config set agents.defaults.model.primary "ollama/qwen3.6:35b-a3b"` revert
given at the end of §5c was never run (or didn't take) — `agents.defaults.model.primary`
was later found to still read `ollama/qwen3:8b`, confirmed by direct query days after the
"revert." This means `qwen3:8b` was live in production the whole time, including through
an unrelated side investigation (below) — which is actually useful: a Signal conversation
from this window surfaced a **third** distinct `qwen3:8b` failure mode, independent of
the repeat-question and fixation ones:

```
"How much for the hotel krone unterstrass?"
-> "I'm not sure about the price for the hotel Krone Unterstrass.
    Would you like me to look it up for you?"
"Yes"
-> [calls ask_documents, correct answer]
```

It asked for permission before calling the tool, on a question it had no reason to
decline — direct contradiction of `SOUL.md`'s explicit instruction ("Never decline a
personal-record question or tell the user to look it up themselves without first calling
this tool"). Not dangerous (it got there eventually, and the final answer was correct),
but real, unprompted friction never seen in any isolated test, on a model that's already
closed per §5c. Revert re-confirmed applied this time, by direct query, not assumed.

**Separately, found and fixed a real, currently-live config bug while debugging the above**:
`sudo journalctl -u ollama -f` (Ollama's own `OLLAMA_DEBUG=1` scheduler log, already set
on the service) showed `runner.num_ctx=4096` for `qwen3.6:35b-a3b` — our
`agents.defaults.models."<model>".params.num_ctx: 8192` override was not just sometimes
wrong (per §5a's `num_ctx=32768` finding) but in this instance silently falling all the
way back to Ollama's bare default, the exact risk `REQUIREMENTS.md` §4 originally flagged
for `qwen3:8b`'s *own* role and never checked here. This is almost certainly a
contributor to the Oct 5 OOM/context-overflow incident (`Doc/step-5-requirements.md`
§5/§5a context) — a smaller real budget than assumed makes compaction trigger more
often, not less. **Fixed at the Ollama service level instead of OpenClaw's**:
`OLLAMA_NUM_CTX=8192` added to `/etc/systemd/system/ollama.service.d/override.conf`
(alongside the existing `OLLAMA_DEBUG=1`), confirmed via the same debug log afterward
showing `runner.num_ctx=8192`. This applies to every model Ollama serves regardless of
which one OpenClaw is configured to use, and doesn't depend on OpenClaw's per-model
config path at all — the more robust fix, given that path has now been shown unreliable
twice.

**This also retroactively confirms §5c's own evidence was solid, not contaminated**: the
"no tool call" result reported against `qwen3:8b` for a repeated Balboa Fence question
mid-way through planning the model-search approach was briefly suspected to be stale test
traffic on the shared Ollama instance; it wasn't — `qwen3:8b` really was still live and
really did fail that exact way, a fourth real occurrence of the same repeat-question
failure mode across two separate live deployment attempts.

### 5e. Brute-force model search — planned, one structural limitation found before building it

A plan exists (not reproduced in full here) to automate pulling, testing, and discarding
candidate tool-capable models in the ~10GB range, scoring heavily on the repeat-question
case (run 10x) given it's the one that's caught every real failure so far. Before
committing hours to it, the scoring logic was validated against the two models with known
ground truth: it correctly should fail `qwen3:8b` and pass `qwen3.6:35b-a3b`. **It scored
both as PASS** — `qwen3:8b` hit 10/10 on the exact repeat-question battery in isolation,
same as every prior isolated test of it, despite being a confirmed, repeated live failure.

**This means the automated Stage 1 filter, as designed, cannot distinguish a real winner
from another `qwen3:8b`** — it can only rule out candidates that fail *cheap, correctness-
level* checks (no `tools` capability, malformed JSON instead of structured calls, wrong
tool selection — real things that already eliminated `mistral`, both `qwen2.5-coder`
sizes, etc. in earlier testing), not confirm reliability under real OpenClaw runtime
conditions. Any future run of this search should be scoped as elimination-only — every
survivor still needs the same live Signal testing that has caught every real failure in
this project so far, with no shortcut around that step.

### 5f. The real fix: drive OpenClaw's own CLI instead of reconstructing its prompt

§5e's limitation is now closed. `openclaw --help` lists `agent` — *"Run an agent turn via
the Gateway (use --local for embedded)"* — which, with `--session-key <isolated-key>`,
`--model <override>`, and no `--deliver`, runs a real agent turn through the actual
running gateway (real workspace files, real injected skills, real tool list, real
sandboxing, real session history) without touching production conversation state and
without ever sending anything to a real channel. Confirmed directly:

```
call 1 (fresh session): tools_called=['hybrid-rag__ask_documents']  -- correct
call 2 (exact repeat, same session): tools_called=[]                -- answered from
    memory, word-for-word identical reply to call 1, 3.5s (vs ~27s for a real lookup)
```

**This reproduced the known `qwen3:8b` repeat-question failure on the first try** —
something no local/synthetic test (including concurrent-load testing) ever managed
across dozens of attempts. The same two-call sequence against `qwen3.6:35b-a3b` as a
control passed both calls. The missing ingredient all along was never prompt content —
every local test's hand-built "fake assistant turn in a messages array" never faithfully
replicated OpenClaw's own real session/history machinery, and that's exactly the gap that
was hiding the failure.

**New things learned from the real response JSON this exposed, that no synthetic test
had modeled**:
- **23 skills get injected into the real system prompt** (`skills.promptChars: 7139` —
  roughly a third of the full 21,646-char system prompt), none of which any test here
  had ever included.
- **The real tool list for this session is 4 tools** — `read`, `write`, `apply_patch`,
  `hybrid-rag__ask_documents` — not the 6-tool set (including `memory_search`) every
  prior test used based on `tools.allow`. That config apparently doesn't map 1:1 to
  what's actually injected per session. Not fully reconciled with §5b's live `memory_search`
  incident (which proves that tool *is* reachable in at least some real session
  contexts) — open question, not blocking.
- **The context math is now exact, not inferred**: `contextTokenBudget: 32768` minus a
  fixed `reserveTokens: 20000` = `promptBudgetBeforeReserve: 12768` — architecturally
  hardcoded for this model, matching numbers seen weeks earlier from the outside.
- **`--model` is itself gated by `agents.defaults.modelPolicy.allow`** — a plain override
  attempt failed with a clear error until the policy was broadened. **Broadened to
  `["ollama/*"]` for the duration of this testing effort; must be restored to
  `["ollama/qwen3.6:35b-a3b"]` when testing concludes** (the exact prior value, confirmed
  by direct query before changing it).

**`scripts/live_agent_test.py`** wraps this as the project's canonical live-reliability
test going forward, superseding any claim of "reliability" from the local-curl approach.
Real cost, not a cheap check: each call is a genuine agent turn against real Ollama
(seconds for a small GPU-resident model, well over a minute for `qwen3.6:35b-a3b`) — trial
counts should be chosen with that in mind, not the trial counts that were affordable when
testing was free.

**This reopens §5c/§5d's "closed question" verdict on `qwen3:8b`.** That conclusion was
reached without this tool. It should be re-examined with it before being trusted further
— not reversed pre-emptively here, since a single repeat-question result isn't the full
picture a closed verdict deserves, but the premise it rested on ("no way to observe the
real request") no longer holds.

### 5g. Survey of already-pulled models via the real mechanism — `llama3.1:8b` is the strongest candidate yet

`scripts/survey_models.py` ran the repeat-question test (via §5f's real `openclaw agent`
mechanism) against every already-pulled model, capturing actual `ollama ps` residency
rather than estimating GPU fit from file size. (One run was invalidated by npabot-u24's
host crashing mid-survey — unrelated to this project; see the chat record. Re-ran clean.)

| model | parameters | real GPU fit | repeat-test |
|---|---|---|---|
| `qwen2.5:7b-instruct` | 7.6B | 100% | FAIL |
| **`llama3.1:8b`** | **8.0B** | **93%** | **PASS** |
| `llama3:8b` | 8.0B | — | hard error: "model does not support tools" |
| `mistral:latest` | 7.2B | 100% | FAIL |
| `qwen2.5:14b-instruct` | 14.8B | 57% | FAIL |
| `qwen2.5-coder:14b` | 14.8B | 57% | FAIL |
| `deepseek-coder-v2:16b` | 15.7B | — | hard error: "model does not support tools" |
| `deepseek-coder:6.7b` | 7B | — | hard error: "model does not support tools" |
| `qwen2.5-coder:32b` | 32.8B | 30% | FAIL (623s for one trial) |
| `qwen3:8b` | 8.2B | 86% | FAIL (known) |
| `qwen3.6:35b-a3b` | 36.0B (MoE, ~3B active/token) | 33% | PASS (current production) |

`llama3.1:8b` was the only new candidate to pass, so it got a full battery, all via the
real mechanism: **10/10** repeat-question (1 trial from the survey + 9 more), **3/3** on
a different real document question from fresh sessions, **4/4 clean** on the garbled-
query/fixation/new-topic adversarial sequence that exposed `qwen3:8b`'s second failure
mode (no fixation, no fabrication, correctly answered a genuinely new question after
nonsense input). One real, consistent flaw found: it calls the tool even for pure
general-knowledge questions ("capital of France") — always gets the right answer, just
wastes a call. Not a correctness bug, and arguably consistent with this project's own
"always ground, never guess" design bias.

16 of 16 real tool-calling decisions correct across every tested dimension, at 93% GPU
(vs. 33%) and 13-18s per call (vs. ~14s-2min+) — the best-evidenced candidate this
project has produced, evaluated far more thoroughly before a live attempt than either
`qwen3:8b` switch was. Not yet live-tested on Signal — that's the next step, with the
same caution as every previous model change here (confirm workspace files current,
switch, test, watch closely, be ready to revert).

**Also found along the way**: `agents.defaults.modelPolicy.allow` was broadened to
`["ollama/*"]` on npabot-u24 to allow `--model` overrides during this survey — restored
to `["ollama/qwen3.6:35b-a3b"]` as part of the revert below.

### 5h. `llama3.1:8b` live test — a new failure mode no test battery checked for

Switched to production, same careful process as every prior attempt. First real question
("Mattias criminal case") worked correctly. **The literal repeat of that same question
entered a genuine runaway loop**: 14+ independent, fully-completed tool calls (each one
correctly retrieving and generating a fresh response — not a stuck/hung single call) over
at least 4 minutes, confirmed by 14 distinct timestamped entries in
`logs/query_<date>.log`, ~15-21s apart, never converging on a final answer. Still active
when checked.

**The gateway's own shutdown got stuck too.** A plain `systemctl --user restart` hung
indefinitely — `systemctl status` showed `deactivating (stop-sigterm)` for over a minute
past when it should have force-timed-out, with the gateway's own log confirming why:
`"still draining active work before stop: queueSize=2 pendingReplies=1 embeddedRuns=1
sessionAdmissions=1"`. Its graceful-drain logic waits on in-flight work with no apparent
upper bound, and a genuinely runaway turn never finishes draining. Had to
`systemctl --user kill --signal=SIGKILL` to actually stop it (which itself partially
errored — "Failed to send signal... to auxiliary processes" — but still succeeded in
killing and restarting the main process via `Restart=always`).

**This is a new, real, disqualifying failure mode, and a real gap in every test built so
far** — §5f/§5g's battery checked whether a *second, separate* turn re-calls the tool
correctly; nothing ever checked whether a single turn might call the tool repeatedly
without ever stopping. `qwen3.6:35b-a3b` has not shown this in any real usage recorded in
this document. Reverted immediately; `agents.defaults.modelPolicy.allow` restored to its
original `["ollama/qwen3.6:35b-a3b"]`.

**Any future live test of a new candidate should explicitly include a repeat-question
case watched live, not just dispatched and checked after the fact** — this failure was
only caught because the question was asked twice in direct succession during active
monitoring, not through any automated harness.

### 5i. Three purpose-built tool-calling fine-tunes, all ruled out with distinct failures

Tried next, specifically chosen as dedicated tool-calling fine-tunes rather than general
chat models with tools bolted on — `llama3-groq-tool-use:8b` (highest published small-
class tool-calling benchmark score), `hermes3:8b` (Nous Research, agentic-focused), and
`granite3.1-dense:8b` (IBM, trained for tool calling). All three confirmed `tools`-
capable after pulling; tested via §5f's real mechanism before touching production
(`agents.defaults.modelPolicy.allow` broadened for testing, restored to
`["ollama/qwen3.6:35b-a3b"]` immediately after — production never switched).

All three failed, each a distinct, clear, reproducible signature:

- **`llama3-groq-tool-use:8b`** — declined outright on one call ("I don't have access to
  your personal documents," no tool call at all), then correctly called the tool on a
  repeat of the same call in a different run. Inconsistent run-to-run, not just
  occasionally imperfect.
- **`hermes3:8b`** — leaked a literal `<SCRATCHPAD>\n{"arguments": ..., "name":
  "hybrid-rag__ask_documents"}` as raw visible text instead of a structured tool call —
  the same malformed-text-instead-of-`tool_calls` bug as `mistral` and the
  `qwen2.5-coder` family (§5g). That text would have gone straight to a real reply.
- **`granite3.1-dense:8b`** — same malformed-text pattern on one call
  (`[[hybrid-rag__ask_documents]] "..."`), and on another **fabricated a completely
  false account number** (`M577123456` instead of the real `PLL69373`), stated
  confidently as fact. The most dangerous failure mode found in this entire search —
  not declining, not malformed, actively wrong and confident about it.

None viable. Every ≤8B model tried across this project's full search — general chat
models and purpose-built tool-calling fine-tunes alike — has failed in one of a small
number of characteristic ways: malformed text instead of structured calls, outright
decline, fabrication, memory-reliance on repeats, or (uniquely, `llama3.1:8b`)
uncontrolled looping. `qwen3.6:35b-a3b` remains the only model that hasn't shown any of
these in real use.

### 5j. 12-18B range: `mistral-nemo` — closest result yet, still two independent failures

`phi4:14b` and `gemma3:12b` both lack the `tools` capability tag entirely — confirmed via
a hard "model does not support tools" error, same class as §5g's `llama3:8b`/
`deepseek-coder` findings. Cleanly eliminated, no further testing needed. `mistral-nemo`
(12.2B) was the one tools-capable candidate in this batch, and the closest result this
entire search has produced short of the disqualified `llama3.1:8b`:

- **70% GPU residency** (vs. 33% for `qwen3.6:35b-a3b`), ~30-35s/call, no looping
  observed across 10 trials (`toolSummary.calls` stayed at 1 every time).
- **9/10 on the repeat-question test** — one real failure, same memory-reliance class as
  `qwen3:8b`'s original problem ("you provided earlier in this conversation").
- Switched to production for a live Signal test anyway, given this was the strongest
  result short of a disqualifying one. **A second, independent, more serious failure
  surfaced on only the third real question**: the visible reply was literally
  `[TOOL_CALLS](What is the furnace filter size?)` — raw leaked tool-call syntax shown as
  the answer — despite our own engine returning a correct, grounded result
  (`Heater-AC/README`) in 10.44s. Whatever went wrong happened *after* a successful
  retrieval, in how the model composed the final reply, and burned over two extra
  minutes (reported "2 minutes, 19 seconds" vs. our engine's 10.44s) before emitting
  garbage.

Reverted immediately. Two independent failure modes (memory-reliance *and* malformed
final-reply composition) in a very short real test is a clear enough signal — not worth
further trials. `qwen3.6:35b-a3b` remains the only model in this entire search without a
confirmed real failure.

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
