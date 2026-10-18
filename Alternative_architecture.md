# Is this the right architecture?

## Why tool-calling has been this hard

The Hybrid RAG core — dense + sparse retrieval, RRF fusion, grounded generation — has
never been the problem. It's fast (sub-2s typically), accurate, and has been validated
thousands of times across this project. Every failure documented in
`Doc/step-5-requirements.md` §5 happened one layer up: in whether OpenClaw's *agent
model* reliably decides to call our tool at all.

That decision turns out to be a much harder ask than it looks, for a specific,
measurable reason. OpenClaw is a general-purpose assistant platform, not a RAG
front-end. A real request to it carries a system prompt with **23 injected skills**
(weather, github, tmux, taskflow...) alongside our one tool, a fixed 32768-token context
budget we cannot override from the outside (three independent attempts failed —
per-model config, a service-level environment variable, and a context-capped model tag),
and its own memory/session machinery that competes with our tool's instructions (the
`SOUL.md` privacy-refusal reflex, the `MEMORY.md` "always use `memory_search`"
directive). None of this is under our control. Every model smaller than ~35B we tested —
general chat models and purpose-built tool-calling fine-tunes alike — failed under these
*real* conditions in one of a handful of characteristic ways: malformed text instead of
a structured tool call, outright decline, memory-reliance on repeated questions,
fabrication, or (twice, independently) failing to ever stop calling the tool. The one
model that's been reliable, `qwen3.6:35b-a3b`, earns that reliability by brute capability,
not by anything we configured — and pays for it in resource contention and OOM risk.

The pattern across ~15 models is not "we haven't found the right one yet." It's that
**reliably delegating to one specific external tool, every time, is harder than it
looks** — and OpenClaw's architecture gives us no lever to make that easier for a
smaller model.

## Is Hybrid RAG + MCP-via-OpenClaw the right shape?

The retrieval engine, yes. The orchestration layer — a heavyweight, multi-skill AI agent
platform as the sole decider of *whether* to even ask our system a question — is the
fragile part, and it's fragile by construction, not by a bug we can still find.

## Alternatives, ranked by expected success

**1. Bypass the LLM decision for the common case (highest expected success).**
Most real questions ("what's my mileage account number," "when did I last fly to X")
are unambiguously document lookups. A lightweight pre-router — intercepting the
incoming Signal message before OpenClaw's agent even runs, using a cheap heuristic or
embedding-similarity check (the same mechanism our own relevance gate already uses
successfully) — can route these directly to `answer_query()`, skipping the unreliable
"will the model remember to call the tool" step entirely. OpenClaw's full agent only
handles genuinely ambiguous or multi-step requests. This doesn't need a better model; it
removes the failure point for the majority of real traffic. Moderate effort, no new
infrastructure — reuses everything already built.

**2. Make this project the Signal endpoint directly, and drop OpenClaw from this path
(high expected success).** `run_server.py` and the CLI already prove the RAG engine
works standalone. A thin `signal-cli` listener forwarding every message straight to
`answer_query()` has no "decide to call a tool" step at all — every message *is* the
query, and the existing relevance gate already handles "this isn't a document
question" gracefully. The cost is losing OpenClaw's other skills on this Signal number,
which may not matter if this number's job is specifically personal-document Q&A.
Low-to-moderate engineering effort; most of the pieces already exist.

**3. Split "decide" from "compose" (moderate expected success).** Keep OpenClaw for
composing natural replies, but use a small, dedicated, narrow classifier — not a full
agentic model — purely to decide yes/no on "should this call `ask_documents`." A binary
classification task is far more tractable than full tool orchestration, and is closer
to what our relevance gate already does well. Still depends on getting a decision model
right, but the surface area needing reliability is much smaller than the current setup.

**4. Keep chasing model/config changes inside OpenClaw (low expected success).**
This is what's been tried for weeks: config overrides, model swaps, workspace-file
fixes. Each fix validated cleanly and then failed live in a new way. The constraints
causing this (fixed context, forced skill injection, no visibility into the real
request until very recently) are OpenClaw's own architecture, not something more
tuning is likely to route around. Worth stopping, not worth escalating further.

## Bottom line

The RAG system works. The mistake is routing every single question through a
general-purpose agent platform's full decision-making loop when most questions don't
need it. Options 1 and 2 remove that dependency instead of trying to make it more
reliable — that's a better bet than continuing the search that's already consumed this
much effort for one working, resource-heavy result.
