"""Sparse leg: SQLite FTS5 search — step-5-requirements.md §2 step 2.

A raw natural-language query can't be handed to FTS5's MATCH as-is: FTS5's query syntax
treats characters like `"`, `-`, `:`, and bareword operators (AND/OR/NOT/NEAR) specially,
so an arbitrary user question could produce a syntax error or an unintended boolean
query rather than a plain keyword search. Tokenizing and re-quoting each term sidesteps
that entirely — every term becomes a literal phrase match, joined with OR for recall
(BM25 still ranks documents matching more/rarer terms higher).
"""
from __future__ import annotations

import re
import sqlite3

_TOKEN_RE = re.compile(r"\w+")


def sanitize_fts5_query(text: str) -> str:
    terms = _TOKEN_RE.findall(text)
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in terms)


def sparse_search(conn: sqlite3.Connection, table: str, query_text: str, limit: int) -> list[dict]:
    q = sanitize_fts5_query(query_text)
    cur = conn.execute(
        f"SELECT chunk_id, text, rel_path, tags, bm25({table}) AS score "
        f"FROM {table} WHERE {table} MATCH ? ORDER BY score LIMIT ?",
        (q, limit),
    )
    return [dict(r) for r in cur.fetchall()]
