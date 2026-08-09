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
from shared.harness_steps import build_route, review_gate
from shared.llm.provider import provider_by_name, NullProvider


class BoundaryCheck(BaseModel):
    violates: bool = Field(description="True only if the deliverable actually asks the tool to do the forbidden thing.")
    reason: str = Field(description="one short sentence")


def _confirm_boundary(provider, tool_id: str, tool_summary: str,
                      deliverable: str, boundary: dict) -> tuple[bool, str]:
    """Ask the LLM whether a keyword-matched boundary is a genuine violation.

    Degradation rule: if no LLM, do NOT auto-refuse on a keyword hit (that over-refuses).
    Return (False, note) so judgment allows the run but records the potential boundary.
    """
    if isinstance(provider, NullProvider):
        return False, f"potential boundary '{boundary['id']}' not confirmed (no LLM); allowed with warning"
    res = provider.extract(
        BoundaryCheck,
        system=(
            f"You are a fit critic for the tool {tool_id} ({tool_summary}). Decide whether the user "
            f"is asking {tool_id} ITSELF to perform the forbidden action described by the boundary. "
            "Merely mentioning a separate, later, or downstream step is NOT a violation (e.g. "
            "'QC the reads before trimming' asks only for QC — the trimming is a different step done "
            f"by a different tool). Set violates=true only if {tool_id} itself is being asked to do "
            "the forbidden thing."
        ),
        prompt=f"Forbidden use (boundary): {boundary['boundary']}\n"
               f"User's requested deliverable: {deliverable}\n"
               f"Is the user asking {tool_id} itself to do the forbidden thing?",
    )
    if res is None:
        return False, f"boundary '{boundary['id']}' inconclusive (LLM parse failed); allowed with warning"
    return res.violates, res.reason


def judgment_node(state: dict) -> dict:
    contract = cl.load_contract(state["tool"])
    spec = state["spec"]
    # one availability check per run: onboarding resolved the (possibly UI-selected) provider
    # and recorded its name in state; rebuild it here without re-checking
    provider = provider_by_name(state.get("llm_provider"))

    # 0) human-review gate: refuse an un-vetted contract (HRR_ markers) before anything else.
    gate = review_gate(contract)
    if gate is not None:
        return {"route": gate.to_dict()}

    # 1) deterministic preconditions
    blocking, warnings = cl.evaluate_preconditions(contract, spec["declared"], spec["measured"])

    # 2) must-not-use boundaries (keyword pre-filter -> LLM confirmation)
    boundary_hits, confirmed = [], []
    tool_id = contract["id"]
    tool_summary = (contract.get("summary") or "").strip()
    for b in cl.match_boundaries(contract, spec["deliverable"]):
        violates, reason = _confirm_boundary(provider, tool_id, tool_summary, spec["deliverable"], b)
        boundary_hits.append(f"{b['id']}: {reason}")
        if violates:
            confirmed.append(b["id"])

    return {"route": build_route(blocking, confirmed, boundary_hits, warnings).to_dict()}
