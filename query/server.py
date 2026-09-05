"""OpenAI-compatible HTTP endpoint — step-5-requirements.md §4 (Open WebUI) and §5
(OpenClaw/Signal, proposed to reuse this same endpoint)."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from query.config import QueryConfig
from query.engine import answer_query

_MODEL_ID = "hybrid-rag"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    stream: Optional[bool] = False  # streaming not implemented — see Open Questions #5


def create_app(config: QueryConfig) -> FastAPI:
    app = FastAPI(title="Hybrid RAG")

    @app.get("/v1/models")
    def list_models():
        return {
            "object": "list",
            "data": [{"id": _MODEL_ID, "object": "model", "owned_by": "local", "created": 0}],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest):
        user_messages = [m for m in req.messages if m.role == "user"]
        query = user_messages[-1].content if user_messages else ""

        result = answer_query(query, config)
        if result.error:
            content = f"Sorry, something went wrong answering that: {result.error}"
        else:
            content = result.answer
            if result.sources:
                cites = "\n".join(f"- {s['rel_path']}" for s in result.sources)
                content = f"{content}\n\nSources:\n{cites}"

        return {
            "id": "chatcmpl-hybridrag",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": _MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }

    return app
