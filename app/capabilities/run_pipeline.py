"""run_pipeline — actually run a tool through the four-harness pipeline, streaming each stage.

Reuses the existing LangGraph pipeline (onboarding -> judgment -> execute -> evaluation|diagnosis).
`graph.stream()` yields one `{node: delta}` per stage; we turn each into a UI-friendly event. A
refusal ends the stream right after judgment — the "right to refuse before compute" made visible.

The graph's nodes select their own provider (auto) internally; honoring the UI provider per-node is a
later refinement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from langgraph_impl.graph import build_graph

# max stdout/stderr tail kept in an execution event (full logs stay in the audit record on disk)
_TAIL = 4000

# expected stages, for the UI progress bar (a refusal short-circuits after judgment; `done` completes it)
PLAN = ["onboarding", "judgment", "execution", "evaluation"]


def stage_events(message: str, tool: str, file: str,
                 provider: str = "auto", out_dir: Optional[str] = None,
                 reference: Optional[str] = None) -> Iterator[tuple[str, dict]]:
    """Blocking generator: yield (node_name, delta) as the pipeline runs. `provider` selects the LLM
    each harness node uses (onboarding/judgment/evaluation), honoring the UI dropdown. `out_dir`, when
    given, is a durable session-scoped output directory (else the execution node mkdtemps one).
    `reference` is the genome FASTA for aligners (a second input)."""
    graph = build_graph()
    state = {"tool": tool, "fastq": file, "question": message, "deliverable": message,
             "provider": provider, "reference": reference}
    if out_dir:
        state["out_dir"] = out_dir
    for update in graph.stream(state):
        for node, delta in update.items():
            yield node, delta


def to_event(stage: str, delta: dict) -> dict:
    """Map a raw pipeline delta to a compact, UI-friendly stage event."""
    if stage == "onboarding":
        m = delta.get("measured", {})
        return {"stage": "onboarding", "title": "Onboarding",
                "facts": {k: m.get(k) for k in ("format", "read_length_mode", "encoding_guess", "layout")},
                "disagreements": delta.get("spec", {}).get("disagreements", [])}
    if stage == "judgment":
        r = delta.get("route", {})
        return {"stage": "judgment", "title": "Judgment (fit critic)",
                "action": r.get("action"), "rationale": r.get("rationale"),
                "confidence": r.get("confidence"),
                "precondition_failures": r.get("precondition_failures", []),
                "boundary_hits": r.get("boundary_hits", [])}
    if stage == "execute":
        rr = delta.get("run_result", {})
        out_dir = rr.get("output_dir") or ""
        return {"stage": "execution", "title": "Execution",
                "ok": rr.get("ok"), "exit_code": rr.get("exit_code"),
                "out_dir": out_dir, "out_name": Path(out_dir).name if out_dir else None,
                "stderr_tail": (rr.get("stderr") or "")[-_TAIL:],
                "error": rr.get("error")}
    if stage == "evaluation":
        v = delta.get("verdict", {})
        return {"stage": "evaluation", "title": "Evaluation", "status": v.get("status"),
                "findings": v.get("findings", []), "metrics": v.get("metrics", {}),
                "explanation": v.get("explanation")}
    if stage == "diagnosis":
        v = delta.get("verdict", {})
        return {"stage": "diagnosis", "title": "Diagnosis", "status": v.get("status"),
                "findings": v.get("findings", []), "proposed_fix": v.get("proposed_fix")}
    return {"stage": stage, "title": stage, "raw": True}


def summary_line(action: Optional[str], verdict_status: Optional[str], tool: str) -> str:
    """Deterministic one-line chat summary once the stream ends."""
    if action == "refuse":
        return f"I refused to run **{tool}** before any compute — see the Judgment stage for why."
    if verdict_status == "ok":
        return f"**{tool}** ran and every scored metric was within its expected range."
    if verdict_status == "anomaly":
        return f"**{tool}** ran, but the Evaluation stage flagged one or more metrics — details on the right."
    if verdict_status == "failure":
        return f"**{tool}** crashed; the Diagnosis stage matched it against known failure modes."
    if verdict_status == "cannot_assess":
        return f"**{tool}** ran, but its output couldn't be scored (Evaluation refused to guess)."
    return f"Finished running **{tool}**."
