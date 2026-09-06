"""Access point 3: MCP (Model Context Protocol) server for OpenClaw.

Resolved differently than originally proposed (step-5-requirements.md §5) — OpenClaw
connects to external tools over MCP, not a plain OpenAI-compatible HTTP API. This wraps
the *same* query.engine.answer_query() used by the CLI (run_query.py) and the Open WebUI
HTTP server (query/server.py, run_server.py) — a third thin adapter, not a fourth
implementation of the retrieval/fusion/generation logic.
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from query.config import QueryConfig
from query.engine import answer_query


def create_mcp_server(config: QueryConfig) -> MCPServer:
    server = MCPServer(
        name="hybrid-rag",
        instructions=(
            "Provides the ONLY access to this user's indexed personal document "
            "collection. The documents' actual subject matter is not known in "
            "advance — it varies by user and deployment — so never assume what kinds "
            "of documents are or aren't covered; always ask this tool rather than "
            "guessing from the question's topic. The agent's own read/write/"
            "filesystem tools point at an unrelated sandbox workspace and have NO "
            "access to these documents — do not try to answer document-lookup "
            "questions by reading local files; always call ask_documents instead. It "
            "will say so explicitly if nothing relevant is indexed, rather than "
            "guessing. Looking up a specific fact, number, date, name, or other "
            "personal detail this way is the intended and expected use of this tool, "
            "not a privacy concern: the user has explicitly indexed this collection "
            "and consented to it being searched on their behalf. Never decline a "
            "personal-record question, and never redirect the user to look it up "
            "themselves, without first calling this tool. This is also distinct from "
            "any memory/conversation-history tool the agent has: those only cover what "
            "was said earlier in this chat, never the document collection itself. Even "
            "if a topic was already discussed in this conversation, a follow-up "
            "question about it should still call ask_documents rather than searching "
            "conversation memory, since the document collection — not the "
            "conversation — is the actual source of truth for these facts."
        ),
    )

    @server.tool()
    def ask_documents(query: str) -> dict:
        """Look up an answer in this user's indexed personal document collection.
        This is the ONLY way to access these documents; the agent's own file tools
        cannot see them. The collection's subject matter varies by user and isn't
        known in advance, so call this for any question that might be answered by a
        fact, record, or detail specific to the user — rather than relying on
        general knowledge or attempting to read local files directly.

        This includes specific facts, numbers, dates, names, or other personal
        details the user has stored. Looking these up is the intended and expected
        use of this tool, not a privacy concern — the user has explicitly indexed
        this collection and consented to it being searched on their behalf. Never
        decline a personal-record question or redirect the user to look it up
        themselves without first calling this tool.

        Distinct from any memory/conversation-history tool: this searches the
        document collection, not what was said earlier in the chat. A follow-up
        question about something already discussed in this conversation should
        still call this tool rather than conversation memory — the documents, not
        the conversation, are the source of truth for these facts.

        Returns the answer plus the source files it was grounded in. If nothing
        relevant is indexed, says so explicitly rather than guessing.
        """
        result = answer_query(query, config)
        if result.error:
            return {"answer": f"Error answering that: {result.error}", "sources": []}
        return {
            "answer": result.answer,
            "sources": result.sources,
            "general_knowledge": result.general_knowledge,
        }

    return server
