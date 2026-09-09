# LONG-TERM MEMORY & KNOWLEDGE BASE

## Workspace Map
- **Knowledge Root**: `./memory/`
- **Daily Logs**: `./memory/YYYY-MM-DD.md`
- **Project Context**: `./memory/projects/`
- **Technical Specs**: `./memory/docs/`

## RAG Directives
- BEFORE answering any question about past conversations, project technicalities, or my preferences, you MUST call `memory_search`.
- If a semantic search returns no results, use `memory_get` to check the `MEMORY.md` file or the most recent daily log.
- Do not assume information is missing just because it is not in your current context window; the workspace folder is the source of truth.
- EXCEPTION: a question about a fact, record, or detail from the user's own personal documents (account numbers, dates, purchases, travel, medical records, etc.) always goes through hybrid-rag__ask_documents instead, never memory_search — even if this or a similar topic came up before, in this conversation or a past one. memory_search is only for questions about this assistant's own conversational history, preferences, or technical decisions, not for facts that live in the user's document collection. If in doubt about which one applies, prefer hybrid-rag__ask_documents.

## Permanent Context
- **User Profile**: [Your Name/Role]
- **Current Goals**: [High-level summary of what you're working on]
- **Tool Preferences**: [e.g., "Prefer Python for scripting", "Use Brave for search"]

## Active Indexing
- This workspace is monitored by the OpenClaw QMD indexer.
- All files in `./memory/` are available for semantic retrieval.
