"""Judgment agent (NOOA) — the fit critic.

Mirrors langgraph_impl/harnesses/judgment.py. Deterministic methods evaluate preconditions and
keyword-match boundaries; the agentic `confirm_boundary` method asks the LLM whether a keyword hit
is a genuine violation. `route` composes the RouteDecision.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from nooa import Agent, strategy
from nooa.strategies import PredictStrategy

from shared import contracts_lib as cl
from shared.models import RouteDecision


class BoundaryCheck(BaseModel):
    violates: bool = Field(description="True only if FastQC itself is asked to do the forbidden thing.")
    reason: str = Field(description="one short sentence")


class JudgmentAgent(Agent):
    """You are a fit critic for FastQC, which ONLY produces quality-control reports (it never
    trims, cleans, aggregates across samples, or identifies organisms). You reject requests that
    would run but be biologically or methodologically wrong."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = cl.load_contract("fastqc")

    # --- deterministic tools ---
    def check_preconditions(self, declared: dict, measured: dict):
        blocking, warnings = cl.evaluate_preconditions(self.contract, declared, measured)
        return blocking, warnings

    def candidate_boundaries(self, deliverable: str):
        return cl.match_boundaries(self.contract, deliverable)

    def route(self, blocking, confirmed, boundary_notes, warnings) -> RouteDecision:
        precondition_failures = [f"{b['id']}: {b.get('message','')}" for b in blocking]
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

    # --- agentic (LLM-driven) method ---
    @strategy(PredictStrategy())
    async def confirm_boundary(self, boundary: str, deliverable: str) -> BoundaryCheck:
        """Decide whether the user is asking FastQC ITSELF to perform the forbidden action in
        `boundary`. Merely mentioning a separate, later, or downstream step is NOT a violation:
        e.g. 'QC the reads before trimming' asks only for QC (allowed) — trimming is a different
        step done by a different tool. Set violates=true only when FastQC itself is asked to do
        the forbidden thing."""
        ...
