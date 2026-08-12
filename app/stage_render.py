"""Framework-free rendering of pipeline stages into UI events.

Maps a harness stage + delta to the compact event shapes the JS UI renders, plus the deterministic
one-line chat summary. Kept separate from `app/capabilities/run_pipeline.py` (which imports LangGraph
to stream the legacy path) so the agent loop can reuse these helpers WITHOUT pulling in a framework —
both the agent loop and the legacy run_pipeline capability import from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# max stdout/stderr tail kept in an execution event (full logs stay in the audit record on disk)
_TAIL = 4000

# expected stages, for the UI progress bar (a refusal short-circuits after judgment; `done` completes it)
PLAN = ["onboarding", "judgment", "execution", "evaluation"]


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
