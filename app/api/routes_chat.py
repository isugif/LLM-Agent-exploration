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
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.llm.provider import get_provider
from shared import dataset
from app import resolve
from app.session import STORE
from app.intent import classify, stub_text
from app.capabilities import describe_data, run_pipeline, add_tool, explain_tool, find_tool, session_query


class ChatRequest(BaseModel):
    message: str
    provider: str | None = None            # 'ollama' | 'claude' | 'auto'/None
    file: str | None = None                # optional explicit file path from the UI
    history: list[dict] = []               # prior turns [{role, content}] for context (memory)
    session_id: str | None = None          # persistent session id (UI localStorage); validated server-side


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
        sid = STORE.ensure(req.session_id)          # validated/minted; echoed back so the UI persists it

        async def _emit(rec):
            yield rec("log", json.dumps({"text": f"Classifying request (model: {provider.name})…"}))
            intent = await run_in_threadpool(classify, req.message, provider, req.history)
            if req.file and not intent.files:            # explicit UI file field
                intent.files = [req.file]
            runs = STORE.load_runs(sid)
            session_ctx = {"has_runs": bool(runs), "tools": sorted({r.get("tool") for r in runs if r.get("tool")})}
            notes = resolve.resolve(intent, req.message, req.history, session_ctx)   # deterministic grounding
            dataset.set_context(f"chat:{intent.intent}")   # tag this turn's LLM calls
            dataset.record("intent", model=provider.name, prompt=req.message,
                           response=intent.intent, labels={"intent": intent.intent})
            yield rec("meta", json.dumps({"provider": provider.name, "intent": intent.intent, "sid": sid}))
            for n in notes:
                yield rec("log", json.dumps({"text": f"grounded: {n}"}))

            # uniform clarifying question when a required slot could not be resolved
            slot = resolve.missing_slot(intent)
            if slot:
                yield rec("prose", json.dumps({"text": resolve.ask_text(slot)}))
                yield rec("done", "{}")
                return

            file = intent.files[0] if intent.files else None

            if intent.intent == "describe_data":
                yield rec("log", json.dumps({"text": f"Profiling {file}…"}))
                result = await run_in_threadpool(describe_data.run, req.message, file, provider)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "run_pipeline":
                tool = intent.tool if intent.tool and intent.tool != "unknown" else "fastqc"
                yield rec("log", json.dumps({"text": f"Running {tool} on {file}…"}))
                yield rec("plan", json.dumps({"steps": run_pipeline.PLAN}))
                out_dir = str(STORE.run_dir(sid, tool))   # durable, under the session dir
                action = verdict_status = None
                metrics: dict = {}
                findings: list = []
                async for kind, payload in _abridge(
                        lambda: run_pipeline.stage_events(req.message, tool, file,
                                                          req.provider or "auto", out_dir)):
                    if kind == "error":
                        yield rec("stage", json.dumps({"stage": "error", "title": "Error", "error": payload}))
                        continue
                    stage, delta = payload
                    ev = run_pipeline.to_event(stage, delta)
                    if ev["stage"] == "judgment":
                        action = ev.get("action")
                    if ev["stage"] in ("evaluation", "diagnosis"):
                        verdict_status = ev.get("status")
                        metrics = ev.get("metrics", {}) or metrics
                        findings = ev.get("findings", []) or findings
                    yield rec("stage", json.dumps(ev))
                STORE.append_run(sid, {"tool": tool, "question": req.message, "file": file,
                                       "out_dir": out_dir, "out_name": Path(out_dir).name,
                                       "action": action, "verdict_status": verdict_status,
                                       "metrics": metrics, "findings": findings})
                yield rec("prose", json.dumps(
                    {"text": run_pipeline.summary_line(action, verdict_status, tool)}))

            elif intent.intent == "add_tool":
                tool = intent.tool.strip().lower()
                yield rec("log", json.dumps({"text": f"Installing + documenting {tool}…"}))
                yield rec("plan", json.dumps({"steps": add_tool.plan_for(tool)}))
                installed, version, markers = False, None, 0
                created, already = [], False
                async for kind, payload in _abridge(
                        lambda: add_tool.stage_events(tool, req.provider or "auto")):
                    if kind == "error":
                        yield rec("stage", json.dumps({"stage": "error", "title": "Error", "error": payload}))
                        continue
                    stage, data = payload
                    if stage == "provision":
                        installed, version = data.get("installed", False), data.get("version")
                    elif stage == "docs_check":
                        already = not data.get("missing")
                    elif stage == "curate" and data.get("status") == "valid":
                        created.append(data.get("section"))
                    elif stage == "hrr_gate":
                        markers = data.get("markers", 0)
                    yield rec("stage", json.dumps(add_tool.to_event(stage, data)))
                yield rec("prose", json.dumps(
                    {"text": add_tool.summary_line(tool, installed, version, markers, created, already)}))

            elif intent.intent == "explain_tool":
                tool = intent.tool.strip().lower()
                yield rec("log", json.dumps({"text": f"Looking up {tool} documentation…"}))
                result = await run_in_threadpool(explain_tool.run, req.message, tool, provider, req.history)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "find_tool":
                yield rec("log", json.dumps({"text": "Searching the tool catalog…"}))
                result = await run_in_threadpool(find_tool.run, req.message, provider)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "session_query":
                yield rec("log", json.dumps({"text": "Recalling this session's runs…"}))
                result = await run_in_threadpool(session_query.run, req.message, sid, provider)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            else:
                yield rec("prose", json.dumps({"text": stub_text(intent)}))

            yield rec("done", "{}")

        async def gen():
            # persist the turn's streamed events even if the client aborts/disconnects mid-stream:
            # a GeneratorExit thrown at the suspended `yield` still runs this finally, so a partial
            # (interrupted) turn saves what it streamed rather than being lost.
            turn_events: list = []       # tee'd for the session transcript (repaint on reload)

            def rec(name: str, data: str) -> str:
                turn_events.append({"event": name, "data": data})
                return _sse(name, data)

            try:
                async for chunk in _emit(rec):
                    yield chunk
            finally:
                if turn_events:
                    STORE.append_turn(sid, {"question": req.message, "events": turn_events})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.get("/api/sessions")
    def list_sessions() -> dict:
        """Prior sessions (newest-first) for the reload/continue picker."""
        return {"sessions": STORE.list_sessions()}

    @router.get("/api/sessions/{sid}/runs")
    def session_runs(sid: str) -> dict:
        """The run history of one session (for reloading it into the panel)."""
        return {"sid": sid, "runs": STORE.load_runs(sid)}

    @router.get("/api/sessions/{sid}/transcript")
    def session_transcript(sid: str) -> dict:
        """The full chat transcript (event stream per turn) to repaint a session on reload."""
        return {"sid": sid, "turns": STORE.load_transcript(sid)}

    @router.get("/api/sessions/{sid}/report")
    def session_report(sid: str, run: str):
        """Serve the HTML report of one run (for the in-app Report tab / open-in-new-tab)."""
        path = STORE.report_file(sid, run)
        if path is None:
            raise HTTPException(status_code=404, detail="no report for that run")
        return FileResponse(str(path), media_type="text/html")

    # -- settings + local training-data harvest ------------------------------

    @router.get("/api/settings")
    def get_settings() -> dict:
        return STORE.get_settings()

    @router.post("/api/settings")
    def set_settings(body: dict) -> dict:
        return STORE.save_settings(body or {})

    @router.get("/api/dataset/stats")
    def dataset_stats() -> dict:
        """Row count + size of the always-on local interaction log (for the settings UI)."""
        return dataset.stats()

    @router.get("/api/dataset/export")
    def dataset_export():
        """Download the local dataset JSONL. It never leaves the machine except when you do this."""
        p = dataset.path()
        if not p.exists():
            raise HTTPException(status_code=404, detail="no dataset collected yet")
        return FileResponse(str(p), media_type="application/x-ndjson", filename="bio_chat_dataset.jsonl")

    return router
