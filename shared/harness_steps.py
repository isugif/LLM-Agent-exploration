"""Framework-agnostic step logic for the four harnesses — the same shared-core pattern as
curator/stages/steps.py.

Both tracks previously carried their own copy of this logic (and the copies had begun to drift:
the NOOA reconcile None-guarded its inputs, the LangGraph one didn't). All judgment-shaped
DETERMINISTIC composition now lives here as pure functions; the LangGraph nodes and the NOOA
agent methods are thin wrappers that only supply their framework's idiom (state-dict merges vs
agent methods). That keeps the framework comparison honest — same behavior, different
orchestration — and makes track parity structural instead of policed.

Nothing here imports langgraph or nooa, and nothing here calls an LLM.
"""

from __future__ import annotations

from typing import Any, Optional

from shared import contracts_lib as cl
from shared.models import RouteDecision, Verdict


# --- onboarding --------------------------------------------------------------

def reconcile(declared: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """Flag declared-vs-measured conflicts — the cheap silent-error catch."""
    d: list[str] = []
    dl = (declared.get("layout", "unknown") or "unknown").upper()
    ml = measured.get("layout", "")
    if dl == "SE" and ml == "PE?":
        d.append("declared single-end but filename looks like a paired mate (_1/_R1).")
    if dl == "PE" and ml == "SE?":
        d.append("declared paired-end but filename does not look like a mate file.")
    if (declared.get("platform", "unknown") or "").lower() == "nanopore" and \
       measured.get("read_length_max", 0) and measured["read_length_max"] < 200:
        d.append("declared nanopore but reads are short (<200bp), which looks like short-read data.")
    return d


# --- judgment ----------------------------------------------------------------

def review_gate(contract: dict[str, Any]) -> Optional[RouteDecision]:
    """Refuse an un-vetted contract (HRR_ markers in machine sections) before anything else."""
    if cl.is_reviewed(contract):
        return None
    markers = cl.find_hrr_markers(contract)
    return RouteDecision(
        action="refuse",
        rationale=f"{contract['id']}'s contract is pending human review "
                  f"({len(markers)} HRR_ marker(s) in machine sections).",
        confidence=1.0,
        precondition_failures=[f"unreviewed: {m}" for m in markers[:3]],
    )


def build_route(blocking: list[dict], confirmed: list[str],
                boundary_notes: list[str], warnings: list[dict]) -> RouteDecision:
    """Compose the RouteDecision from precondition + boundary outcomes."""
    precondition_failures = [f"{b['id']}: {b.get('message', '')}" for b in blocking]
    if blocking or confirmed:
        parts = precondition_failures + [f"confirmed boundary: {c}" for c in confirmed]
        return RouteDecision(
            action="refuse",
            rationale="Contract violation(s): " + "; ".join(parts),
            confidence=0.9 if blocking else 0.7,
            precondition_failures=precondition_failures,
            boundary_hits=boundary_notes,
        )
    note = "preconditions satisfied; no confirmed boundary violations."
    if warnings:
        note += " warnings: " + "; ".join(w["id"] for w in warnings)
    return RouteDecision(action="run", rationale=note, confidence=0.8, boundary_hits=boundary_notes)


# --- diagnosis (hard failures) -------------------------------------------------

def diagnose_run(contract: dict[str, Any], *, stdout: Optional[str], stderr: Optional[str],
                 error: Optional[str], exit_code: Optional[int]) -> Verdict:
    """Match a failed run's audit trail against the contract's failure_modes; escalate novelty."""
    haystack = "\n".join([stderr or "", stdout or "", error or ""]).lower()
    for fm in contract.get("failure_modes", []):
        if fm["signal"].lower() in haystack:
            return Verdict(
                status="failure",
                findings=[f"matched failure mode '{fm['id']}' (signal: {fm['signal']!r})"],
                proposed_fix=fm["fix"], escalate=False,
            )
    if error and "not found on PATH" in error:
        hint = contract.get("execution", {}).get("install_hint", "")
        return Verdict(status="failure", findings=[f"{contract['id']} is not installed"],
                       proposed_fix=f"Install {contract['id']}: `{hint}`.", escalate=False)
    return Verdict(
        status="failure",
        findings=[f"unrecognized failure (exit={exit_code}). stderr tail: " + (stderr or "")[-300:]],
        proposed_fix=None, escalate=True,   # novel crash -> human curation
    )


# --- evaluation (soft failures) ------------------------------------------------

def score_metrics(expectations: dict[str, Any], metrics: dict[str, Any]) -> tuple[dict, list[str]]:
    """Score each expectation-table metric present in `metrics`; return (scored, findings)."""
    scored, findings = {}, []
    for name in expectations.get("metrics", {}):        # scored metrics come from the contract
        if name in metrics:
            s = cl.score_metric(expectations, name, metrics[name])
            scored[name] = s
            if s["tier"] in ("warn", "fail"):
                note = f" ({s['note']})" if s["note"] else ""
                findings.append(f"{name}={s['value']} -> {s['tier'].upper()}{note}")
    return scored, findings


def evaluation_verdict(metrics: dict[str, Any], scored: dict, findings: list[str],
                       explanation: Optional[str]) -> Verdict:
    """Compose the evaluation Verdict; unparseable output refuses (`cannot_assess`), never 'ok'."""
    if "error" in metrics:
        return Verdict(status="cannot_assess", findings=[metrics["error"]], escalate=True)
    return Verdict(status="ok" if not findings else "anomaly",
                   findings=findings or ["all scored metrics within expected ranges"],
                   explanation=explanation, metrics=scored, escalate=False)
