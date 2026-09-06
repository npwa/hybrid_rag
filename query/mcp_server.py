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
            "guessing."
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
