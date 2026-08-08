"""POST /api/chat — classify the message, dispatch, stream the result over SSE.

Two shapes of capability:
  * describe_data — single-shot: emit one `panel` event + `prose`.
  * run_pipeline  — streaming: emit a `stage` event per harness stage as the pipeline runs, then a
    deterministic `prose` summary. The blocking graph generator is bridged to async via a thread+queue.

Provider is chosen per request ('ollama' | 'claude' | 'auto').
"""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.llm.provider import get_provider
from app.intent import classify, stub_text
from app.capabilities import describe_data, run_pipeline, add_tool


class ChatRequest(BaseModel):
    message: str
    provider: str | None = None            # 'ollama' | 'claude' | 'auto'/None
    file: str | None = None                # optional explicit file path from the UI


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _abridge(make_gen):
    """Run a blocking generator in a thread, yielding its items on the event loop via a queue."""
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker():
        try:
            for item in make_gen():
                loop.call_soon_threadsafe(q.put_nowait, ("item", item))
        except Exception as exc:             # noqa: BLE001 - surface as an error event, don't hang
            loop.call_soon_threadsafe(q.put_nowait, ("error", str(exc)))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, ("end", None))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        kind, payload = await q.get()
        if kind == "end":
            return
        yield kind, payload


def make_chat_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat")
    async def chat(req: ChatRequest):
        provider = get_provider(req.provider)

        async def gen():
            yield _sse("log", json.dumps({"text": f"Classifying request (model: {provider.name})…"}))
            intent = await run_in_threadpool(classify, req.message, provider)
            file = req.file or (intent.files[0] if intent.files else None)
            yield _sse("meta", json.dumps({"provider": provider.name, "intent": intent.intent}))

            if intent.intent == "describe_data":
                yield _sse("log", json.dumps({"text": f"Profiling {file or '(no file given)'}…"}))
                result = await run_in_threadpool(describe_data.run, req.message, file, provider)
                if result.get("panel") is not None:
                    yield _sse("panel", json.dumps(result["panel"]))
                yield _sse("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "run_pipeline":
                tool = intent.tool if intent.tool and intent.tool != "unknown" else "fastqc"
                if not file:
                    yield _sse("prose", json.dumps(
                        {"text": "Which file should I run it on? Give me a FASTQ path."}))
                else:
                    yield _sse("log", json.dumps({"text": f"Running {tool} on {file}…"}))
                    yield _sse("plan", json.dumps({"steps": run_pipeline.PLAN}))
                    action = verdict_status = None
                    async for kind, payload in _abridge(
                            lambda: run_pipeline.stage_events(req.message, tool, file, req.provider or "auto")):
                        if kind == "error":
                            yield _sse("stage", json.dumps(
                                {"stage": "error", "title": "Error", "error": payload}))
                            continue
                        stage, delta = payload
                        ev = run_pipeline.to_event(stage, delta)
                        if ev["stage"] == "judgment":
                            action = ev.get("action")
                        if ev["stage"] in ("evaluation", "diagnosis"):
                            verdict_status = ev.get("status")
                        yield _sse("stage", json.dumps(ev))
                    yield _sse("prose", json.dumps(
                        {"text": run_pipeline.summary_line(action, verdict_status, tool)}))

            elif intent.intent == "add_tool":
                tool = (intent.tool or "").strip().lower()
                if not tool or tool == "unknown":
                    yield _sse("prose", json.dumps(
                        {"text": "Which tool should I install? e.g. \"install seqkit\"."}))
                else:
                    yield _sse("log", json.dumps({"text": f"Installing + documenting {tool}…"}))
                    yield _sse("plan", json.dumps({"steps": add_tool.plan()}))
                    installed = False
                    version = None
                    markers = 0
                    async for kind, payload in _abridge(
                            lambda: add_tool.stage_events(tool, req.provider or "auto")):
                        if kind == "error":
                            yield _sse("stage", json.dumps(
                                {"stage": "error", "title": "Error", "error": payload}))
                            continue
                        stage, data = payload
                        if stage == "provision":
                            installed, version = data.get("installed", False), data.get("version")
                        if stage == "hrr_gate":
                            markers = data.get("markers", 0)
                        yield _sse("stage", json.dumps(add_tool.to_event(stage, data)))
                    yield _sse("prose", json.dumps(
                        {"text": add_tool.summary_line(tool, installed, version, markers)}))

            else:
                yield _sse("prose", json.dumps({"text": stub_text(intent)}))

            yield _sse("done", "{}")

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
