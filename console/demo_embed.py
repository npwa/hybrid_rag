"""A tiny deterministic text embedder for the synthetic demo dataset (NOT semantic, NOT nomic-embed-text).

Feature hashing of lower-cased words into 768 signed buckets, L2-normalised, so a query that shares words with a
chunk lands close to it. Lets the demo run the real LanceDB search, relevance gate and RRF fusion with no Ollama.
Used by scripts/make_synthetic_data.py (chunk vectors) and by the explorer in --demo mode (query vectors)."""
from __future__ import annotations

import hashlib
import re

DIM = 768
_STOP = {"a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "i", "in", "is", "it",
         "of", "on", "or", "the", "to", "was", "what", "when", "where", "which", "who", "with", "my", "me"}


def embed_text(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if tok in _STOP:
            continue
        h = int(hashlib.sha1(tok.encode()).hexdigest()[:8], 16)
        vec[h % DIM] += 1.0 if (h >> 20) & 1 else -1.0
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        vec[0], norm = 1.0, 1.0
    return [x / norm for x in vec]


def embed_batch(texts: list[str], _config=None) -> list[list[float]]:
    """Same call shape as indexing.embedder.embed_batch(texts, config)."""
    return [embed_text(t) for t in texts]
