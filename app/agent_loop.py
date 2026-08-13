"""Agentic tool-use loop — the model-agnostic replacement for the intent/resolve brain.

The model may chat, read/query the working folder, and REQUEST tools; it can never execute a raw
command. The only way to run a bioinformatics tool is `run_tool`, which self-guards via
shared/pipeline.py (onboarding -> judgment -> refuse|execute -> evaluate|diagnose). No shell / no
arbitrary code / no writes outside a run's out_dir is ever offered.

Driven through `provider.extract(AgentAction, ...)` — the one primitive BOTH OllamaProvider and
ClaudeCLIProvider already implement — so the loop is model-agnostic and needs no native tool-calling
API.

This is the DEFAULT chat brain whenever a model is reachable (Claude CLI preferred, else Ollama).
With no model, POST /api/chat falls back to the deterministic regex router (app/resolve.py); the
retired LLM classifier (app/intent.py) is gone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, Field

from shared import catalog as catalog_lib
from shared import pipeline
from shared.probes.fastq_probe import probe as _fastq_probe
from shared.probes.aln_probe import probe_alignment as _aln_probe
from shared.probes.report_dir_probe import probe_report_dir as _report_dir_probe
from shared.llm.provider import NullProvider
from app import workdir
from app import stage_render
from app.session import STORE

_REPO_DATA = Path(__file__).resolve().parents[1] / "shared" / "data"
MAX_STEPS = 10             # headroom for inspect + run_tool across several files; guards stop earlier
_READ_CAP = 4000            # bytes returned by read_file (head only; enough to identify a file)


class AgentAction(BaseModel):
    """One step the model proposes: either call a tool, or answer and stop."""
    thought: str = Field(default="", description="one short sentence of reasoning")
    tool: Optional[str] = Field(default=None, description="tool name to call, or null to answer now")
    args: dict = Field(default_factory=dict, description="arguments for the tool")
    answer: Optional[str] = Field(default=None, description="final answer to the user when tool is null")


# --- read-only helpers ---------------------------------------------------------

def _probe_path(path: str) -> dict[str, Any]:
    if os.path.isdir(path):
        return _report_dir_probe(path)
    if path.lower().endswith((".bam", ".sam", ".cram")):
        return _aln_probe(path)
    return _fastq_probe(path)


_LISTALL = 100000     # inspect() sample cap high enough to list EVERY file (matching needs the full set)


def _workdir_groups() -> dict[str, list[str]]:
    """All working-folder files grouped by kind (full lists — not the 8-file preview sample)."""
    try:
        return {g["kind"]: g.get("files", [])
                for g in workdir.inspect(sample=_LISTALL).get("groups", [])}
    except Exception:                             # noqa: BLE001
        return {}


def _fastq_names() -> list[str]:
    """Every FASTQ filename in the working folder (surfaced to the model for continuity)."""
    return _workdir_groups().get("fastq", [])


def _takes_report_dir(tool: str) -> bool:
    """True if the tool aggregates a DIRECTORY of reports (e.g. MultiQC) rather than a single file."""
    from shared.tools.registry import PROBES
    from shared.probes.report_dir_probe import probe_report_dir
    return PROBES.get(tool) is probe_report_dir


def _input_candidates(tool: str) -> list[str]:
    """Working-folder files valid as INPUTS for this tool: alignments for alignment-consuming tools,
    else FASTQs. Used to expand a pattern deterministically — the model never enumerates files."""
    from shared.tools.registry import PROBES
    from shared.probes.aln_probe import probe_alignment
    groups = _workdir_groups()
    if PROBES.get(tool) is probe_alignment:
        return groups.get("alignment", [])
    return groups.get("fastq", [])


def _match_names(pattern: str, names: list[str]) -> list[str]:
    """Deterministic file selection: fnmatch on the BASENAME (files may be listed as 'data/x.fastq.gz',
    so an anchored glob like 'snf*.fastq.gz' must match the filename, not the dir prefix),
    case-insensitive; a bare token like 'snf' -> '*snf*'."""
    import fnmatch
    pat = (pattern if any(c in pattern for c in "*?[") else f"*{pattern}*").lower()
    return [n for n in names if fnmatch.fnmatch(os.path.basename(n).lower(), pat)]


def _scoped_read(path: str, max_bytes: int = _READ_CAP) -> dict[str, Any]:
    """Read the head of a file, but ONLY within the working directory (or repo demo data). Read-only,
    size-capped — this is the 'query over folder contents' capability without a write/exec path."""
    real = os.path.realpath(workdir.resolve_path(path) or path)
    roots = [os.path.realpath(str(workdir.get_workdir())), os.path.realpath(str(_REPO_DATA))]
    if not any(real == r or real.startswith(r + os.sep) for r in roots):
        return {"error": "path is outside the working directory (read-only scope)"}
    if not os.path.isfile(real):
        return {"error": f"not a file: {path}"}
    with open(real, "rb") as fh:
        blob = fh.read(max_bytes + 1)
    return {"path": real, "truncated": len(blob) > max_bytes,
            "text": blob[:max_bytes].decode("utf-8", "replace")}


# --- tool registry (name -> (description, handler)) ----------------------------
# Each handler(args, ctx) -> (events, observation). `events` are (sse_name, data) pairs streamed to
# the UI; `observation` is the compact fact dict fed back to the model for its next step.

def _t_list_workdir(args, ctx):
    panel = workdir.inspect()                    # {workdir, n_files, groups:[{kind,count,files}]}
    return [("panel", {"kind": "folder", **panel})], panel


def _t_read_file(args, ctx):
    out = _scoped_read(args.get("path", ""), int(args.get("max_bytes", _READ_CAP)))
    return [], out


def _t_probe_data(args, ctx):
    path = workdir.resolve_path(args.get("path", "")) or args.get("path", "")
    facts = _probe_path(path)
    panel = {"kind": "data", "file": path,
             "facts": [{"label": k, "value": v} for k, v in facts.items()]}
    return [("panel", panel)], facts


def _t_list_catalog(args, ctx):
    if args.get("category") or args.get("input_format") or args.get("text"):
        recs = catalog_lib.find(category=args.get("category"), input_format=args.get("input_format"),
                                text=args.get("text"))
    else:
        recs = catalog_lib.catalog()
    tools = [{"tool": r.get("tool"), "summary": r.get("summary"),
              "categories": r.get("category_tags", []),
              "input_formats": r.get("input_formats", []),
              "output_formats": r.get("output_formats", []),
              "reviewed": r.get("reviewed")} for r in recs]
    return [("panel", {"kind": "catalog", "count": len(tools), "tools": tools})], \
        {"tools": [t["tool"] for t in tools]}


def _t_explain_tool(args, ctx):
    from app.capabilities import explain_tool as cap
    out = cap.run(message=f"explain {args.get('tool')}", tool=args.get("tool"), provider=NullProvider())
    panel = out.get("panel")
    events = [("panel", panel)] if panel else []
    return events, {"panel": panel}


def _t_find_tool(args, ctx):
    from app.capabilities import find_tool as cap
    out = cap.run(message=args.get("query", ""), provider=NullProvider())
    panel = out.get("panel")
    events = [("panel", panel)] if panel else []
    return events, {"panel": panel}


def _t_list_outputs(args, ctx):
    """This session's completed runs + the files in each output directory — so the model can CHAIN
    tools (feed one tool's output into the next, e.g. minimap2's BAM into rustqc)."""
    runs = STORE.load_runs(ctx["sid"])
    items, panel_runs = [], []
    for r in runs:
        out = r.get("out_dir")
        files = []
        if out and os.path.isdir(out):
            files = sorted(os.path.relpath(os.path.join(dp, f), out)
                           for dp, _, fs in os.walk(out) for f in fs)[:25]
        items.append({"tool": r.get("tool"), "out_dir": out, "out_name": r.get("out_name"),
                      "action": r.get("action"), "verdict": r.get("verdict_status"), "files": files})
        panel_runs.append({"tool": r.get("tool"), "out_dir": out, "out_name": r.get("out_name"),
                           "action": r.get("action"), "verdict": r.get("verdict_status"),
                           "when": (r.get("ts") or "").replace("T", " ")})
    panel = {"kind": "session", "count": len(panel_runs), "runs": list(reversed(panel_runs))}
    return [("panel", panel)], {"runs": items}


def _run_tool_stage_events(result: dict) -> Iterator[tuple[str, dict]]:
    """Rebuild the UI staged events from a shared/pipeline result, reusing run_pipeline.to_event so
    the Activity panel looks identical — but sourced from shared/pipeline (no LangGraph)."""
    yield "stage", stage_render.to_event("onboarding",
                                             {"measured": result.get("measured", {}), "spec": result.get("spec", {})})
    yield "stage", stage_render.to_event("judgment", {"route": result.get("route", {})})
    if result.get("run_result") is not None:
        yield "stage", stage_render.to_event("execute", {"run_result": result["run_result"]})
        last = result.get("trace", [])[-1] if result.get("trace") else None
        if last == "evaluation":
            yield "stage", stage_render.to_event("evaluation", {"verdict": result.get("verdict", {})})
        elif last == "diagnosis":
            yield "stage", stage_render.to_event("diagnosis", {"verdict": result.get("verdict", {})})


def _resolve_run_inputs(tool: str, args: dict, ctx: dict) -> tuple[list[str], str]:
    """Deterministically resolve the input path(s) for a run_tool call — so the MODEL only expresses
    intent (a pattern, or nothing for an aggregator) and the harness does the file selection."""
    # aggregator tools consume a DIRECTORY of reports; default to this session's runs/ dir.
    if _takes_report_dir(tool):
        d = args.get("path") or args.get("dir")
        d = workdir.resolve_path(d) if d else None
        if not (d and os.path.isdir(d)):
            d = str(STORE.runs_dir(ctx["sid"]))
        return [d], f"aggregating reports in {d}"
    # an explicit list of files
    paths = args.get("paths")
    if isinstance(paths, list) and paths:
        return [workdir.resolve_path(p) or p for p in paths], f"{len(paths)} file(s) given"
    # a pattern -> deterministic glob over the tool's valid inputs (runs EVERY match in one call)
    pattern = (args.get("pattern") or "").strip()
    if pattern:
        matches = _match_names(pattern, _input_candidates(tool))
        return ([workdir.resolve_path(m) or m for m in matches],
                f"pattern '{pattern}' matched {len(matches)} file(s)")
    # a single file
    path = args.get("path")
    if path:
        return [workdir.resolve_path(path) or path], ""
    return [], "no file, pattern, or paths given"


def _run_one(tool: str, path: str, ctx: dict, question: str, reference=None, annotation=None,
             declared=None, provider_name=None) -> tuple[list, dict]:
    """Run ONE input through the gate, idempotent per turn. `declared` reuses already-extracted facts
    (skips onboarding's LLM call — the batch cost saver). Returns (events, per-file result)."""
    done = ctx.setdefault("done", {})
    key = os.path.realpath(path)
    if key in done:                               # already ran this file this turn -> no-op
        d = done[key]
        return ([("log", {"text": f"already ran {tool} on {Path(path).name}; not repeating"})],
                {"path": path, "route": d["route"], "verdict": d["verdict"], "skipped": True,
                 "declared": d.get("declared"), "llm_provider": d.get("llm_provider")})
    out_dir = str(STORE.run_dir(ctx["sid"], tool))
    result = pipeline.run_pipeline(
        tool=tool, fastq=path, question=question,
        reference=workdir.resolve_path(reference), annotation=workdir.resolve_path(annotation),
        out_dir=out_dir, provider=provider_name or ctx["provider_name"],
        provider_model=ctx.get("provider_model"), declared=declared)
    action = result.get("route", {}).get("action")
    verdict = (result.get("verdict") or {}).get("status")
    metrics = (result.get("verdict") or {}).get("metrics", {}) or {}
    findings = (result.get("verdict") or {}).get("findings", []) or []
    events: list = [("plan", {"steps": stage_render.PLAN})]
    for name, ev in _run_tool_stage_events(result):
        events.append((name, ev))
    STORE.append_run(ctx["sid"], {"tool": tool, "question": ctx["message"], "file": path,
                                  "out_dir": out_dir, "out_name": Path(out_dir).name,
                                  "action": action, "verdict_status": verdict,
                                  "metrics": metrics, "findings": findings})
    done[key] = {"path": path, "route": action, "verdict": verdict,
                 "declared": result.get("declared"), "llm_provider": result.get("llm_provider")}
    events.append(("log", {"text": stage_render.summary_line(action, verdict, tool)}))
    return events, {"path": path, "route": action, "verdict": verdict, "findings": findings,
                    "out_dir": out_dir, "declared": result.get("declared"),
                    "llm_provider": result.get("llm_provider")}


def _batch_summary(tool: str, ran: list[dict]) -> str:
    if len(ran) == 1:
        return stage_render.summary_line(ran[0]["route"], ran[0]["verdict"], tool)
    parts = ", ".join(f"{Path(r['path']).name} ({r['route']}/{r['verdict'] or '—'})" for r in ran)
    return f"Ran **{tool}** on {len(ran)} file(s): {parts}."


def _t_run_tool(args, ctx):
    """Run a tool on one file, a glob `pattern` (every match in ONE call), a `paths` list, or — for an
    aggregator like multiqc — the session's run outputs by default. File selection is deterministic."""
    tool = (args.get("tool") or "").strip().lower()
    paths, note = _resolve_run_inputs(tool, args, ctx)
    if not paths:
        return ([("log", {"text": f"run_tool: {note}"})],
                {"error": note, "available_fastq": _fastq_names()})
    question = args.get("question") or ctx["message"]
    events: list = [("log", {"text": f"→ {tool}: {note}"})] if note else []
    ran: list[dict] = []
    # Extract declared facts ONCE per batch: the first file's onboarding does the LLM call, the rest
    # reuse its declared facts (same question) — so a 3-file batch is 1 onboarding LLM call, not 3.
    declared_cache = None
    prov_cache = ctx["provider_name"]
    for p in paths:
        evs, res = _run_one(tool, p, ctx, question, reference=args.get("reference"),
                            annotation=args.get("annotation"),
                            declared=declared_cache, provider_name=prov_cache)
        events.extend(evs)
        ran.append(res)
        if declared_cache is None and res.get("declared") is not None:
            declared_cache = res["declared"]                       # reuse for the remaining files
            prov_cache = res.get("llm_provider") or prov_cache
    events.append(("log", {"text": _batch_summary(tool, ran)}))
    observation = {"ran": [{"file": Path(r["path"]).name, "route": r["route"], "verdict": r["verdict"]}
                           for r in ran],
                   "completed": [d["path"] for d in ctx.get("done", {}).values()],
                   "available_fastq": _fastq_names()}
    return events, observation


def _t_describe_data(args, ctx):
    """Rich FASTQ profile (measured facts + read-length/quality plots) — the describe_data capability
    as an agent tool. Deterministic; the agent narrates from the returned facts."""
    from app.capabilities import describe_data as cap
    path = workdir.resolve_path(args.get("path", "")) or args.get("path", "")
    out = cap.run(args.get("question") or f"profile {path}", path, NullProvider())
    panel = out.get("panel")
    events = [("panel", panel)] if panel else []
    obs = {"facts": (panel or {}).get("facts"), "disagreements": (panel or {}).get("disagreements")}
    return events, obs


def _t_session_query(args, ctx):
    """Natural-language recall over this session's runs (where an output went, what a verdict was)."""
    from app.capabilities import session_query as cap
    out = cap.run(args.get("query") or ctx["message"], ctx["sid"], NullProvider())
    panel = out.get("panel")
    events = [("panel", panel)] if panel else []
    return events, {"answer": out.get("prose"), "panel_kind": (panel or {}).get("kind")}


def _t_add_tool(args, ctx):
    """Install + document a new tool via the curator (HRR-gated: documented but NOT runnable until a
    human reviews its safety contract). Streams the curator stages."""
    from app.capabilities import add_tool as cap
    tool = (args.get("tool") or "").strip().lower()
    events: list = [("plan", {"steps": cap.plan_for(tool)})]
    installed, version, markers, created, already = False, None, 0, [], False
    for stage, data in cap.stage_events(tool, ctx.get("provider_name") or "auto"):
        if stage == "provision":
            installed, version = data.get("installed", False), data.get("version")
        elif stage == "docs_check":
            already = not data.get("missing")
        elif stage == "curate" and data.get("status") == "valid":
            created.append(data.get("section"))
        elif stage == "hrr_gate":
            markers = data.get("markers", 0)
        events.append(("stage", cap.to_event(stage, data)))
    events.append(("log", {"text": cap.summary_line(tool, installed, version, markers, created, already)}))
    obs = {"installed": installed, "version": version, "hrr_markers": markers, "sections_created": created,
           "note": "documented but NOT runnable until a human reviews the HRR_ machine sections"}
    return events, obs


TOOLS: dict[str, tuple[str, Any]] = {
    "list_workdir": ("List the INPUT working folder grouped by file type (fastq, alignment, fasta, …). No args.", _t_list_workdir),
    "list_outputs": ("List this session's completed runs and the files in each OUTPUT directory. Use "
                     "this to chain tools — feed one tool's output into the next. No args.", _t_list_outputs),
    "read_file": ("Read the head of a text file in the working folder. args: path, [max_bytes]. Read-only.", _t_read_file),
    "probe_data": ("Measured facts about a data path (FASTQ / alignment / report dir). args: path.", _t_probe_data),
    "describe_data": ("Rich FASTQ profile: measured facts + read-length/quality plots. args: path.", _t_describe_data),
    "list_catalog": ("List/filter documented tools. args (all optional): category, input_format, text.", _t_list_catalog),
    "explain_tool": ("Curated facts about one documented tool. args: tool.", _t_explain_tool),
    "find_tool": ("Find candidate tools for a need. args: query.", _t_find_tool),
    "session_query": ("Recall this session's past runs (where output went, what a verdict was). args: query.", _t_session_query),
    "add_tool": ("Install + document a NEW tool via the curator (HRR-gated; documented but not runnable "
                 "until human-reviewed). args: tool.", _t_add_tool),
    "run_tool": ("THE only way to run a bioinformatics tool. Self-guards (onboarding+judgment) and may "
                 "REFUSE. Give `tool` and ONE of: `path` (one file), `pattern` (e.g. 'snf' or "
                 "'*.fastq.gz' — runs the tool on EVERY matching input file in a SINGLE call), or "
                 "`paths` (list). Aggregators like multiqc need no path (they default to this session's "
                 "run outputs). Optional: question, reference, annotation.", _t_run_tool),
}

_DEGRADED = ("No language model is reachable, so I can't drive the conversation. The deterministic "
             "harness still works — set a provider (Ollama/Claude) or use an explicit request.")


def _system_prompt() -> str:
    lines = [
        "You are a bioinformatics assistant. You help a scientist inspect data and run tools SAFELY.",
        "You may read and query the working folder, and you may REQUEST tools — but you can never run "
        "a raw shell command. The ONLY way to execute a bioinformatics tool is the run_tool tool, "
        "which itself checks fitness and may refuse. Never claim a tool ran unless run_tool says so.",
        "",
        "Each step, return JSON for ONE action: either call a tool (set `tool` and `args`) or finish "
        "(set `tool` to null and put your reply in `answer`). Available tools:",
    ]
    for name, (desc, _) in TOOLS.items():
        lines.append(f"  - {name}: {desc}")
    lines += [
        "",
        "Rules:",
        "  - If you don't know the filenames, call list_workdir FIRST.",
        "  - To run a tool on MANY files (e.g. 'all snf files'), pass a `pattern` to run_tool ONCE — it "
        "runs every match in a single call. Do NOT loop run_tool file-by-file.",
        "  - Aggregators (e.g. multiqc) take no path — call run_tool with just the tool name; it "
        "defaults to this session's run outputs.",
        "  - When the request is satisfied, STOP: set tool to null and summarize in `answer`. Don't "
        "re-run files already listed in `completed`.",
    ]
    return "\n".join(lines)


def run_agent(message: str, history: list[dict], provider, sid: str) -> Iterator[tuple[str, dict]]:
    """Drive the tool-use loop, yielding (sse_event_name, data) pairs. Terminal event is ('prose', …)
    followed by ('done', {}). SSE event names match the existing UI: log/meta/panel/plan/stage/prose."""
    yield "meta", {"provider": getattr(provider, "name", "null"),
                   "model": getattr(provider, "model", None), "mode": "agent", "sid": sid}
    if isinstance(provider, NullProvider) or getattr(provider, "name", "null") == "null":
        yield "prose", {"text": _DEGRADED}
        yield "done", {}
        return

    system = _system_prompt()
    ctx = {"sid": sid, "message": message, "provider_name": getattr(provider, "name", None),
           "provider_model": getattr(provider, "model", None), "done": {}}
    transcript = _format_history(history)
    observations: list[str] = []
    seen: dict[str, int] = {}                     # action signature -> times proposed (loop guard)

    for step in range(MAX_STEPS):
        prompt = transcript + f"\nUser: {message}\n"
        if observations:
            prompt += "\nObservations so far:\n" + "\n".join(observations) + "\n"
        prompt += "\nYour next action (JSON):"
        # One retry with a stricter nudge: local models occasionally emit an unparseable step (extra
        # prose, a stray <think> block). A second attempt recovers most of them. The retry only fires
        # when the first returned None, so it never slows a successful step.
        action = provider.extract(AgentAction, system=system, prompt=prompt)
        if action is None:
            action = provider.extract(
                AgentAction, system=system,
                prompt=prompt + "\n\nReturn ONLY a single JSON object for one action — no prose, no "
                                "<think>, no code fence.")
        if action is None:
            yield "prose", {"text": _finish_summary(ctx, "I couldn't form a valid next step.")}
            yield "done", {}
            return

        if not action.tool:                       # model chose to finish
            yield "prose", {"text": action.answer or _finish_summary(ctx, "Done.")}
            yield "done", {}
            return

        name = action.tool.strip()
        if name not in TOOLS:
            observations.append(f"[{name}] error: unknown tool; choose from {list(TOOLS)}")
            yield "log", {"text": f"ignored unknown tool '{name}'"}
            continue

        sig = name + "|" + _compact(action.args, 200)
        seen[sig] = seen.get(sig, 0) + 1
        if seen[sig] >= 3:                         # persistent identical repetition -> stop cleanly
            yield "prose", {"text": _finish_summary(ctx, "Stopping — the model kept repeating a step.")}
            yield "done", {}
            return

        yield "log", {"text": f"→ {name}({_compact(action.args)})"}
        try:
            events, observation = TOOLS[name][1](action.args, ctx)
        except Exception as exc:                  # noqa: BLE001 - surface, don't hang the stream
            observations.append(f"[{name}] error: {exc}")
            yield "stage", {"stage": "error", "title": "Error", "error": str(exc)}
            continue
        for ev_name, ev_data in events:
            yield ev_name, ev_data
        observations.append(f"[{name}] -> {_compact(observation)}")

    yield "prose", {"text": _finish_summary(ctx, "Reached the step limit.")}
    yield "done", {}


def _finish_summary(ctx: dict, prefix: str = "") -> str:
    """Deterministic close-out: what actually ran this turn, regardless of how the loop ended."""
    done = ctx.get("done", {})
    if done:
        items = ", ".join(f"{Path(d['path']).name} ({d['route']}/{d['verdict'] or '—'})"
                          for d in done.values())
        body = f"Ran {len(done)} file(s): {items}."
    else:
        body = "No tools were run."
    return (prefix + " " + body).strip()


def _format_history(history: list[dict]) -> str:
    turns = [f"{t.get('role', 'user')}: {(t.get('content') or '').strip()}"
             for t in (history or [])[-6:] if (t.get('content') or '').strip()]
    return "\n".join(turns)


def _compact(obj: Any, limit: int = 600) -> str:
    try:
        s = json.dumps(obj, default=str)
    except Exception:                             # noqa: BLE001
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "…"
