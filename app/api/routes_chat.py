"""POST /api/chat — route the message to the right brain and stream the result over SSE.

Routing (chosen per request from the provider dropdown, default 'auto'):
  * model reachable  -> the agentic tool-use loop (app/agent_loop.py); Claude CLI preferred, else Ollama.
  * no model         -> the deterministic regex router (app/resolve.py): grounds a bare Intent() and
    dispatches to a capability. Works fully offline; the LLM classifier is retired.

Capability shapes (deterministic path): describe_data/explain_tool/... single-shot (one `panel` +
`prose`); run_pipeline streams a `stage` per harness stage (blocking graph bridged to async).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.llm.provider import (NullProvider, OllamaProvider, ClaudeCLIProvider, ollama_available,
                                 OLLAMA_HOST, OLLAMA_MODEL)
from shared import catalog, contracts_lib as cl, dataset
from app import resolve
from app.session import STORE

# Claude CLI model aliases offered in the UI dropdown. The CLI resolves aliases to the current
# version, so the list never goes stale; None/"" means the CLI's own default.
_CLAUDE_MODELS = ["opus", "sonnet", "haiku"]


def _chat_provider(name: str | None, model: str | None = None):
    """Pick the chat brain at an optional specific model. Explicit 'ollama'/'claude' if reachable;
    'auto'/None prefers the Claude CLI (subscription, no API key), then Ollama, then NullProvider
    (which routes to the deterministic regex fallback). This is the ONLY place the chat's Claude-first
    default lives — the global get_provider('auto') stays Ollama-first for the CLI/tests/harness."""
    model = model or None                          # normalize "" -> None (provider default)
    if name == "ollama":
        return OllamaProvider(model=model or OLLAMA_MODEL) if ollama_available() else NullProvider()
    if name == "claude":
        p = ClaudeCLIProvider(model=model)
        return p if p.is_available() else NullProvider()
    p = ClaudeCLIProvider(model=model)            # auto / None: Claude first
    if p.is_available():
        return p
    return OllamaProvider(model=model or OLLAMA_MODEL) if ollama_available() else NullProvider()


def _resolve_tool_name(name: str) -> str | None:
    """Map a user-typed tool name to a DOCUMENTED tool: exact (case-insensitive, spaces->underscores
    so 'samtools sort' -> 'samtools_sort'), else a unique prefix/substring match ('minimap' ->
    'minimap2'). None if nothing matches — so an unknown tool is handled gracefully instead of
    crashing on a missing manifest."""
    docs = catalog.available_tools()
    low = (name or "").strip().lower().replace(" ", "_")
    if not low:
        return None
    for t in docs:
        if t.lower() == low:
            return t
    hits = [t for t in docs if t.lower().startswith(low) or low in t.lower()]
    return hits[0] if len(hits) == 1 else None


def _tool_extra_inputs(tool: str) -> tuple[bool, bool, bool]:
    """(needs_reference, needs_annotation, consumes_alignment) — data-driven from the tool's contract
    argv + input probe, so the chat knows what to resolve/ask for."""
    from shared.tools.registry import PROBES
    from shared.probes.aln_probe import probe_alignment
    try:
        argv = cl.load_contract(tool).get("execution", {}).get("argv", [])
    except Exception:  # noqa: BLE001
        argv = []
    joined = " ".join(argv)
    return ("{reference}" in joined, "{annotation}" in joined,
            PROBES.get(tool) is probe_alignment)


def _tool_takes_report_dir(tool: str) -> bool:
    """True if the tool aggregates a DIRECTORY of reports (MultiQC) rather than a single file —
    so its input should be resolved as a directory, defaulting to the session's runs/ dir."""
    from shared.tools.registry import PROBES
    from shared.probes.report_dir_probe import probe_report_dir
    return PROBES.get(tool) is probe_report_dir


def _existing_path(p: str | None) -> str | None:
    """Resolve a user-typed data path against the active working directory (app/workdir.py) — the
    folder the app was launched in, or one set from chat — with a shared/data fallback for demos."""
    return workdir.resolve_path(p)
from app import workdir
from app import agent_loop
from app.capabilities import (describe_data, run_pipeline, add_tool, explain_tool, find_tool,
                              session_query, workdir_cmd)


class ChatRequest(BaseModel):
    message: str
    provider: str | None = None            # 'ollama' | 'claude' | 'auto'/None
    model: str | None = None               # specific model (Ollama tag or Claude alias); None = default
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
        provider = _chat_provider(req.provider, req.model)
        sid = STORE.ensure(req.session_id)          # validated/minted; echoed back so the UI persists it

        async def _emit(rec):
            # Default brain: the agentic tool-use loop whenever a model is reachable (Claude CLI
            # preferred, else Ollama). With NO model we fall back to the deterministic regex router
            # (app/resolve.py) so the chat still works offline — the LLM classifier is retired.
            if not isinstance(provider, NullProvider):
                async for kind, payload in _abridge(
                        lambda: agent_loop.run_agent(req.message, req.history, provider, sid)):
                    if kind == "error":
                        yield rec("stage", json.dumps({"stage": "error", "title": "Error", "error": payload}))
                        continue
                    ev_name, data = payload
                    yield rec(ev_name, json.dumps(data))
                return

            # --- deterministic fallback (no model) — grounded by regex, no LLM classify ---
            yield rec("log", json.dumps({"text": "No model reachable — deterministic mode."}))
            intent = resolve.Intent()
            if req.file and not intent.files:            # explicit UI file field
                intent.files = [req.file]
            runs = STORE.load_runs(sid)
            session_ctx = {"has_runs": bool(runs), "tools": sorted({r.get("tool") for r in runs if r.get("tool")})}
            notes = resolve.resolve(intent, req.message, req.history, session_ctx)   # deterministic grounding

            # aggregator tools (MultiQC) take a DIRECTORY of reports, not a typed filename. Use an
            # explicit path from the message, else default to THIS session's runs/ dir so "run
            # multiqc" just aggregates everything run so far. Also satisfies the file slot so the
            # router doesn't ask for a FASTQ (and never back-fills a stale one from history).
            if intent.intent == "run_pipeline":
                _named = intent.tool if intent.tool and intent.tool != "unknown" else "fastqc"
                _tool = _resolve_tool_name(_named)
                if _tool and _tool_takes_report_dir(_tool):
                    d = _existing_path(resolve.path_in(req.message))
                    if not (d and os.path.isdir(d)):
                        d = str(STORE.runs_dir(sid))
                    intent.files = [d]
                    notes.append(f"{_tool} input dir = {d}")

            dataset.set_context(f"chat:{intent.intent}")   # tag this turn's LLM calls
            dataset.record("intent", model=provider.name, prompt=req.message,
                           response=intent.intent, labels={"intent": intent.intent})
            yield rec("meta", json.dumps({"provider": provider.name, "intent": intent.intent,
                                          "model": getattr(provider, "model", None),
                                          "mode": "deterministic", "sid": sid}))
            for n in notes:
                yield rec("log", json.dumps({"text": f"grounded: {n}"}))

            # uniform clarifying question when a required slot could not be resolved
            slot = resolve.missing_slot(intent)
            if slot:
                yield rec("prose", json.dumps({"text": resolve.ask_text(slot)}))
                yield rec("done", "{}")
                return

            file = _existing_path(intent.files[0]) if intent.files else None

            if intent.intent == "describe_data":
                yield rec("log", json.dumps({"text": f"Profiling {file}…"}))
                result = await run_in_threadpool(describe_data.run, req.message, file, provider)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "run_pipeline":
                named = intent.tool if intent.tool and intent.tool != "unknown" else "fastqc"
                tool = _resolve_tool_name(named)
                if tool is None:              # unknown/undocumented tool -> don't crash; guide instead
                    docs = ", ".join(catalog.available_tools()) or "(none yet)"
                    yield rec("prose", json.dumps({"text":
                        f"I don't have a documented tool called **{named}**. Documented tools: {docs}. "
                        f"You can add one with \"install {named}\"."}))
                    yield rec("done", "{}")
                    return
                if tool != named:
                    yield rec("log", json.dumps({"text": f"resolved '{named}' → {tool}"}))
                needs_ref, needs_ann, takes_aln = _tool_extra_inputs(tool)
                # an alignment-consuming tool takes a BAM/SAM/CRAM as its input, not a FASTQ
                if takes_aln and not (file and file.lower().endswith((".bam", ".sam", ".cram"))):
                    file = _existing_path(resolve.aln_in(req.message)) or file
                reference = _existing_path(resolve.fasta_ref_in(req.message))
                annotation = _existing_path(resolve.gtf_in(req.message))
                # onboarding requests: a required second input is asked for, never defaulted
                if takes_aln and not file:
                    yield rec("prose", json.dumps({"text":
                        f"**{tool}** works on an alignment — give me a BAM/SAM/CRAM path."}))
                    yield rec("done", "{}"); return
                if file and not os.path.exists(file):     # clear "not found" beats a format refusal
                    yield rec("prose", json.dumps({"text":
                        f"I can't find `{file}` in `{workdir.get_workdir()}`. Put it in your working "
                        "directory, give a full path, or point me at the folder with "
                        "\"my data is in /path/to/folder\"."}))
                    yield rec("done", "{}"); return
                if needs_ref and not reference:
                    yield rec("prose", json.dumps({"text":
                        f"**{tool}** aligns to a reference genome — which reference? Give me a FASTA path "
                        "(e.g. `shared/data/NC_045512.2.fasta`)."}))
                    yield rec("done", "{}"); return
                if needs_ann and not annotation:
                    yield rec("prose", json.dumps({"text":
                        f"**{tool}** needs a gene annotation — which GTF? Give me a path "
                        "(e.g. `shared/data/Saccharomyces_cerevisiae.R64-1-1.genes.gtf`)."}))
                    yield rec("done", "{}"); return
                yield rec("log", json.dumps({"text": f"Running {tool} on {file}…"}))
                yield rec("plan", json.dumps({"steps": run_pipeline.PLAN}))
                out_dir = str(STORE.run_dir(sid, tool))   # durable, under the session dir
                action = verdict_status = None
                metrics: dict = {}
                findings: list = []
                async for kind, payload in _abridge(
                        lambda: run_pipeline.stage_events(req.message, tool, file,
                                                          req.provider or "auto", out_dir,
                                                          reference, annotation)):
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

            elif intent.intent == "describe_workdir":
                yield rec("log", json.dumps({"text": f"Inspecting {workdir.get_workdir()}…"}))
                result = await run_in_threadpool(workdir_cmd.describe_run)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            elif intent.intent == "set_workdir":
                result = await run_in_threadpool(workdir_cmd.set_run, req.message)
                if result.get("panel") is not None:
                    yield rec("panel", json.dumps(result["panel"]))
                yield rec("prose", json.dumps({"text": result.get("prose", "")}))

            else:
                yield rec("prose", json.dumps({"text": resolve.stub_text(intent)}))

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

    # -- model picker: installed Ollama models + Claude CLI aliases ----------

    @router.get("/api/models")
    def list_models() -> dict:
        """Models the UI can offer per provider: installed Ollama tags (live) + Claude CLI aliases.
        Empty ollama list when the server is down — the dropdown just shows the default option then."""
        ollama: list[str] = []
        try:
            import requests as _rq
            r = _rq.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            r.raise_for_status()
            ollama = sorted(m["name"] for m in r.json().get("models", []) if m.get("name"))
        except Exception:                    # noqa: BLE001 - Ollama down / unreachable
            ollama = []
        return {"ollama": ollama, "claude": list(_CLAUDE_MODELS),
                "defaults": {"ollama": OLLAMA_MODEL}}

    # -- working directory (the folder data paths resolve against) -----------

    @router.get("/api/workdir")
    def get_workdir() -> dict:
        return {"workdir": str(workdir.get_workdir())}

    @router.post("/api/workdir")
    def set_workdir(body: dict) -> dict:
        ok, msg = workdir.set_workdir((body or {}).get("workdir", ""))
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"workdir": str(workdir.get_workdir()), "message": msg}

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
