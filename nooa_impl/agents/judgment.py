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
from shared.harness_steps import build_route as _build_route, review_gate as _review_gate
from shared.models import RouteDecision


class BoundaryCheck(BaseModel):
    violates: bool = Field(description="True only if the named tool itself is asked to do the forbidden thing.")
    reason: str = Field(description="one short sentence")


class JudgmentAgent(Agent):
    """You are a fit critic for bioinformatics tools. You reject requests that would run but be
    biologically or methodologically wrong, judging the named tool against its stated purpose."""

    def __init__(self, tool_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_id = tool_id
        self.contract = cl.load_contract(tool_id)

    # --- deterministic tools (thin wrappers over shared.harness_steps) ---
    def review_gate(self) -> RouteDecision | None:
        """Refuse an un-vetted contract (HRR_ markers in machine sections) before anything else."""
        return _review_gate(self.contract)

    def check_preconditions(self, declared: dict, measured: dict):
        blocking, warnings = cl.evaluate_preconditions(self.contract, declared, measured)
        return blocking, warnings

    def candidate_boundaries(self, deliverable: str):
        return cl.match_boundaries(self.contract, deliverable)

    def route(self, blocking, confirmed, boundary_notes, warnings) -> RouteDecision:
        return _build_route(blocking, confirmed, boundary_notes, warnings)

    # --- agentic (LLM-driven) method ---
    @strategy(PredictStrategy())
    async def confirm_boundary(self, tool_id: str, tool_summary: str,
                               boundary: str, deliverable: str) -> BoundaryCheck:
        """You are a fit critic for `tool_id` (purpose: `tool_summary`). Decide whether the user's
        `deliverable` asks `tool_id` ITSELF to do the forbidden thing described in `boundary`.

        Rules:
        - If the deliverable asks for a result that `boundary` says this tool must not produce, that
          IS a violation (violates=true) — even if the tool could emit related-looking numbers.
        - Merely mentioning a separate, later, or downstream step is NOT a violation: e.g. 'QC the
          reads before trimming' asks only for QC (allowed); trimming is a different tool's job.

        Set violates=true only when `tool_id` itself is being asked to do the forbidden thing."""
        ...
