"""POST /api/chat — classify the message, dispatch, stream the result over SSE.

Streams two event types: `panel` (JSON for the right-hand data panel) then `prose` (the assistant's
text). The LLM calls are blocking (subprocess/HTTP), so the dispatch runs in a threadpool to keep the
event loop free. Provider is chosen per request ('ollama' | 'claude' | 'auto').
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.llm.provider import get_provider
from app.intent import classify, stub_text
from app.capabilities import describe_data


class ChatRequest(BaseModel):
    message: str
    provider: str | None = None            # 'ollama' | 'claude' | 'auto'/None
    file: str | None = None                # optional explicit file path from the UI


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _dispatch(req: ChatRequest) -> dict:
    """Blocking: classify + run the matched capability. Returns {panel, prose}."""
    provider = get_provider(req.provider)
    intent = classify(req.message, provider)
    if intent.intent != "describe_data":
        return {"panel": None, "prose": stub_text(intent), "provider": provider.name,
                "intent": intent.intent}
    file = req.file or (intent.files[0] if intent.files else None)
    result = describe_data.run(req.message, file, provider)
    result["provider"] = provider.name
    result["intent"] = intent.intent
    return result


def make_chat_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat")
    async def chat(req: ChatRequest):
        result = await run_in_threadpool(_dispatch, req)

        async def gen():
            yield _sse("meta", json.dumps({"provider": result.get("provider"),
                                           "intent": result.get("intent")}))
            if result.get("panel") is not None:
                yield _sse("panel", json.dumps(result["panel"]))
            yield _sse("prose", json.dumps({"text": result.get("prose", "")}))
            yield _sse("done", "{}")

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
