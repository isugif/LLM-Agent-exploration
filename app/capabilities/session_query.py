"""session_query — recall over THIS session's run-log ("where did I write the fastqc output?",
"what were the results?", "what have I run?").

Deterministic lookup over app.session.STORE, not semantic RAG: the run records already hold the
answer (out_dir, verdict, metrics), so we map the question to the right record + facet and report
it — the LLM (if any) only narrates, grounded strictly in the log. Never invents a run.

Returns {"panel": {kind: 'session', ...} | None, "prose": str}.
"""

from __future__ import annotations

import re
from typing import Optional

from app.session import STORE
from app.resolve import tool_in

# which facet of a run the question asks about
_WHERE_RE = re.compile(r"\b(where|which dir|directory|folder|path|out_?dir|output|wrote|saved|write)\b", re.I)
_RESULT_RE = re.compile(r"\b(result|results|verdict|summary|metric|metrics|score|finding|findings|outcome)\b", re.I)
_LIST_RE = re.compile(r"\b(what have i|what did i|which|list|history|all|everything|so far|runs?)\b", re.I)

NARRATE_SYSTEM = (
    "You answer from a bioinformatics session's run-log ONLY. Use just the records provided below; "
    "never invent a run, path, or result. Answer the user's question in 1-3 sentences, quoting the "
    "exact tool, output directory, or verdict from the log."
)


def _when(rec: dict) -> str:
    return (rec.get("ts") or "").replace("T", " ").replace("+00:00", " UTC")


def _panel(runs: list[dict]) -> dict:
    return {
        "kind": "session",
        "count": len(runs),
        "runs": [{
            "tool": r.get("tool"),
            "when": _when(r),
            "action": r.get("action"),
            "verdict": r.get("verdict_status"),
            "out_dir": r.get("out_dir"),
            "question": r.get("question"),
        } for r in reversed(runs)],   # newest first for display
    }


def _latest_for(runs: list[dict], tool: Optional[str]) -> Optional[dict]:
    for r in reversed(runs):
        if tool is None or (r.get("tool") == tool):
            return r
    return None


def _where_answer(rec: dict) -> str:
    od = rec.get("out_dir") or "(no output directory recorded)"
    return f"You ran **{rec.get('tool')}** {_when(rec)} — its output is in `{od}`."


def _result_answer(rec: dict) -> str:
    tool, verdict = rec.get("tool"), rec.get("verdict_status")
    if rec.get("action") == "refuse":
        return f"**{tool}** was refused before compute {_when(rec)} — it did not run."
    parts = [f"**{tool}** {_when(rec)} → verdict **{verdict or 'unknown'}**."]
    metrics = rec.get("metrics") or {}
    if metrics:
        flags = [f"{k}={v.get('value')} ({v.get('tier')})" for k, v in metrics.items()
                 if isinstance(v, dict)]
        if flags:
            parts.append("Metrics: " + ", ".join(flags) + ".")
    if rec.get("findings"):
        parts.append("Findings: " + "; ".join(rec["findings"]) + ".")
    parts.append(f"Output: `{rec.get('out_dir')}`.")
    return " ".join(parts)


def run(message: str, sid: str, provider) -> dict:
    """Answer a recall question about the current session's runs."""
    runs = STORE.load_runs(sid)
    if not runs:
        return {"panel": None,
                "prose": "You haven't run anything in this session yet. Try "
                         "\"run fastqc on <your.fastq>\"."}

    tool = tool_in(message)                    # a named tool narrows the lookup
    panel = _panel(runs)

    # facet routing (deterministic). where/output -> path; result/verdict -> verdict+metrics.
    if _WHERE_RE.search(message) and not _RESULT_RE.search(message):
        rec = _latest_for(runs, tool)
        if rec is None:
            return {"panel": panel, "prose": f"I don't see a run of **{tool}** in this session."}
        return {"panel": panel, "prose": _where_answer(rec)}

    if _RESULT_RE.search(message):
        rec = _latest_for(runs, tool)
        if rec is None:
            return {"panel": panel, "prose": f"I don't see a run of **{tool}** in this session."}
        return {"panel": panel, "prose": _result_answer(rec)}

    # a specific tool named without a clear facet -> its latest run summary
    if tool:
        rec = _latest_for(runs, tool)
        if rec is None:
            return {"panel": panel, "prose": f"I don't see a run of **{tool}** in this session."}
        return {"panel": panel, "prose": _result_answer(rec)}

    # otherwise: list what has been run (optionally narrated by the LLM, grounded in the log)
    n = len(runs)
    if getattr(provider, "name", "null") == "null" or not _LIST_RE.search(message):
        latest = runs[-1]
        lead = (f"This session has {n} run{'s' if n != 1 else ''}. "
                f"Most recent: {_result_answer(latest)}")
        return {"panel": panel, "prose": lead}
    log = "\n".join(f"- {_when(r)} {r.get('tool')} -> {r.get('verdict_status') or r.get('action')} "
                    f"(out: {r.get('out_dir')})" for r in runs)
    prose = provider.complete(NARRATE_SYSTEM, f"Run-log:\n{log}\n\nQuestion: {message}")
    return {"panel": panel, "prose": prose}
