"""Judgment harness (LangGraph node) — the fit critic.

Tests the spec against the FastQC contract BEFORE any compute:
  1. deterministic preconditions (assert expressions over declared/measured facts),
  2. must-not-use boundaries vs the requested deliverable (cheap keyword pre-filter, then the LLM
     CONFIRMS whether a keyword hit is a real violation — so "QC before trimming" isn't a false
     refusal just because it contains "trim").

Emits a RouteDecision with the right to REFUSE. A blocking precondition failure or a confirmed
boundary violation => refuse, no compute.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared import contracts_lib as cl
from shared.models import RouteDecision
from shared.llm.provider import get_provider, NullProvider


class BoundaryCheck(BaseModel):
    violates: bool = Field(description="True only if the deliverable actually asks the tool to do the forbidden thing.")
    reason: str = Field(description="one short sentence")


def _confirm_boundary(provider, deliverable: str, boundary: dict) -> tuple[bool, str]:
    """Ask the LLM whether a keyword-matched boundary is a genuine violation.

    Degradation rule: if no LLM, do NOT auto-refuse on a keyword hit (that over-refuses).
    Return (False, note) so judgment allows the run but records the potential boundary.
    """
    if isinstance(provider, NullProvider):
        return False, f"potential boundary '{boundary['id']}' not confirmed (no LLM); allowed with warning"
    res = provider.extract(
        BoundaryCheck,
        system=(
            "You are a fit critic for the tool FastQC, which ONLY produces quality-control reports "
            "(it never trims, cleans, aggregates, or identifies organisms). Decide whether the user "
            "is asking FastQC ITSELF to perform the forbidden action described by the boundary. "
            "Merely mentioning a separate, later, or downstream step is NOT a violation. For example, "
            "'QC the reads before trimming' asks only for QC (allowed); the trimming is a different "
            "step done by a different tool. Set violates=true only if FastQC itself is being asked to "
            "do the forbidden thing."
        ),
        prompt=f"Forbidden use (boundary): {boundary['boundary']}\n"
               f"User's requested deliverable: {deliverable}\n"
               f"Is the user asking FastQC itself to do the forbidden thing?",
    )
    if res is None:
        return False, f"boundary '{boundary['id']}' inconclusive (LLM parse failed); allowed with warning"
    return res.violates, res.reason


def judgment_node(state: dict) -> dict:
    contract = cl.load_contract("fastqc")
    spec = state["spec"]
    provider = get_provider()

    # 1) deterministic preconditions
    blocking, warnings = cl.evaluate_preconditions(contract, spec["declared"], spec["measured"])
    precondition_failures = [f"{b['id']}: {b.get('message','')}" for b in blocking]

    # 2) must-not-use boundaries (keyword pre-filter -> LLM confirmation)
    boundary_hits, confirmed = [], []
    for b in cl.match_boundaries(contract, spec["deliverable"]):
        violates, reason = _confirm_boundary(provider, spec["deliverable"], b)
        boundary_hits.append(f"{b['id']}: {reason}")
        if violates:
            confirmed.append(b["id"])

    if blocking or confirmed:
        parts = precondition_failures + [f"confirmed boundary: {c}" for c in confirmed]
        route = RouteDecision(
            action="refuse",
            rationale="Contract violation(s): " + "; ".join(parts),
            confidence=0.9 if blocking else 0.7,
            precondition_failures=precondition_failures,
            boundary_hits=boundary_hits,
        )
    else:
        note = "preconditions satisfied; no confirmed boundary violations."
        if warnings:
            note += " warnings: " + "; ".join(w["id"] for w in warnings)
        route = RouteDecision(
            action="run", rationale=note, confidence=0.8,
            boundary_hits=boundary_hits,
        )
    return {"route": route.to_dict()}
