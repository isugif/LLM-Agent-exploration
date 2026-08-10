"""Onboarding harness (LangGraph node).

Produces the structured spec by reconciling DECLARED facts (parsed from the question by the LLM)
against MEASURED facts (probed from the file). Disagreements are recorded, not silently resolved.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.tools.registry import get_probe
from shared.models import Spec
from shared.harness_steps import reconcile
from shared.llm.provider import get_provider, NullProvider


class DeclaredFacts(BaseModel):
    """What the scientist asserts about their data (LLM-extracted from the question)."""
    platform: str = Field(description="sequencing platform: illumina, nanopore, pacbio, or unknown")
    assay: str = Field(description="assay type: rna-seq, dna-seq, amplicon, wgs, or unknown")
    layout: str = Field(description="library layout: SE, PE, or unknown")
    organism: str = Field(description="organism if stated, else unknown")


def onboarding_node(state: dict) -> dict:
    measured = get_probe(state["tool"])(state["fastq"])
    measured["has_reference"] = bool(state.get("reference"))    # aligner reference-required gate
    measured["has_annotation"] = bool(state.get("annotation"))  # rustqc gtf-required gate
    provider = get_provider(state.get("provider"))

    declared: dict = {}
    if not isinstance(provider, NullProvider):
        parsed = provider.extract(
            DeclaredFacts,
            system="You extract sequencing metadata from a scientist's request. "
                   "Only use what is stated; use 'unknown' when not stated.",
            prompt=state["question"],
        )
        if parsed is not None:
            declared = parsed.model_dump()

    disagreements = reconcile(declared, measured)
    spec = Spec(
        question=state["question"],
        deliverable=state.get("deliverable", state["question"]),
        declared=declared,
        measured=measured,
        disagreements=disagreements,
    )
    return {
        "measured": measured,
        "declared": declared,
        "spec": spec.to_dict(),
        "llm_provider": provider.name,
    }
