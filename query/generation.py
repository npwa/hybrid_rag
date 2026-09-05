"""Prompt building + Ollama chat generation — step-5-requirements.md §2 steps 4-5."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from query.config import QueryConfig

_SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions using only the provided source "
    "excerpts below. Cite the sources you used by their [N] marker. If the answer is "
    "not contained in the excerpts, say you don't know rather than guessing."
)

# Opt-in fallback (query/relevance.py gates when this is used) — deliberately does NOT
# get to blend with document-grounded content: it's a completely separate prompt path
# with no excerpts attached, so there's no way for the model to mix a fabricated detail
# into what looks like a sourced answer.
_GENERAL_KNOWLEDGE_SYSTEM_PROMPT = (
    "The user's personal document collection does not contain anything relevant to "
    "this question. Answer from your own general knowledge instead."
)
_GENERAL_KNOWLEDGE_PREFIX = "General knowledge (not from your documents):\n\n"


class GenerationError(Exception):
    pass


def build_prompt(query: str, chunks: list[dict]) -> tuple[str, str]:
    blocks = [f"[{i}] Source: {c['rel_path']}\n{c['text']}" for i, c in enumerate(chunks, start=1)]
    context = "\n\n".join(blocks)
    user = f"Source excerpts:\n\n{context}\n\nQuestion: {query}"
    return _SYSTEM_PROMPT, user


def build_general_knowledge_prompt(query: str) -> tuple[str, str]:
    return _GENERAL_KNOWLEDGE_SYSTEM_PROMPT, query


def label_general_knowledge(answer: str) -> str:
    """Prepend the fallback-mode flag in code, not just via the prompt — guarantees
    it's always visible regardless of whether the model would have mentioned it
    unprompted."""
    return _GENERAL_KNOWLEDGE_PREFIX + answer


def generate_answer(system: str, user: str, config: QueryConfig) -> str:
    payload = {
        "model": config.generation_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": config.think,
        # Ollama defaults to a 4K context window under the 24GiB VRAM tier — this
        # would silently truncate a RAG prompt without an explicit override (see
        # step-5-requirements.md §2 step 5).
        "options": {"num_ctx": config.num_ctx},
    }
    req = urllib.request.Request(
        f"{config.ollama_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.generation_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise GenerationError(f"could not reach Ollama at {config.ollama_url}: {e}") from e
    except json.JSONDecodeError as e:
        raise GenerationError(f"Ollama returned non-JSON response: {e}") from e

    content = body.get("message", {}).get("content")
    if not content:
        raise GenerationError(f"unexpected response shape from Ollama /api/chat: {body}")
    return content
