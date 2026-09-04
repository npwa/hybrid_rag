"""Ollama embedding calls — batched, stdlib HTTP only (no new dependency; §5 of
REQUIREMENTS.md left this open, resolved here since urllib is sufficient for a single
JSON POST/response)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from indexing.config import IndexConfig


class EmbeddingError(Exception):
    pass


def embed_batch(texts: list[str], config: IndexConfig) -> list[list[float]]:
    """Embed a batch of texts in one Ollama call. Raises EmbeddingError on any failure
    (connection refused, timeout, bad response shape) — callers treat a whole batch as
    failed together and leave those chunks `pending` for retry (§5 of the Step 4 doc)."""
    payload = json.dumps({"model": config.embedding_model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        f"{config.ollama_url}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.embed_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise EmbeddingError(f"could not reach Ollama at {config.ollama_url}: {e}") from e
    except json.JSONDecodeError as e:
        raise EmbeddingError(f"Ollama returned non-JSON response: {e}") from e

    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise EmbeddingError(
            f"unexpected response shape from Ollama /api/embed: expected {len(texts)} "
            f"embeddings, got {embeddings if not isinstance(embeddings, list) else len(embeddings)}"
        )
    return embeddings
