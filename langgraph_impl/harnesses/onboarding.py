"""Onboarding harness (LangGraph node) — thin adapter over shared.harnesses.onboarding.

The step logic lives in shared/harnesses/onboarding.py (single source shared with the MCP
order-guard). This node only unpacks the LangGraph state dict and passes the partial-state dict
straight back for LangGraph to merge.
"""

from __future__ import annotations

from shared.harnesses.onboarding import DeclaredFacts, onboard   # noqa: F401 (re-export)


def onboarding_node(state: dict) -> dict:
    return onboard(
        tool=state["tool"],
        fastq=state["fastq"],
        question=state["question"],
        deliverable=state.get("deliverable"),
        reference=state.get("reference"),
        annotation=state.get("annotation"),
        provider_name=state.get("provider"),
        provider_model=state.get("provider_model"),
    )
