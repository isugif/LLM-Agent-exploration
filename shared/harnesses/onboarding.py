"""Onboarding harness (framework-neutral).

Produces the structured spec by reconciling DECLARED facts (parsed from the question by the LLM)
against MEASURED facts (probed from the file). Disagreements are recorded, not silently resolved.
"""

from __future__ import annotations

from typing import Optional

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


def onboard(*, tool: str, fastq: str, question: str, deliverable: Optional[str] = None,
            reference: Optional[str] = None, annotation: Optional[str] = None,
            provider_name: Optional[str] = None, provider_model: Optional[str] = None) -> dict:
    """Probe the input, extract declared facts, reconcile, and build the spec.

    `provider_name` selects the LLM provider once for the run ("ollama" | "claude" | "auto"/None);
    the resolved provider's name is returned as `llm_provider` so downstream checkpoints rebuild it
    without re-checking availability.
    """
    measured = get_probe(tool)(fastq)
    measured["has_reference"] = bool(reference)     # aligner reference-required gate
    measured["has_annotation"] = bool(annotation)   # rustqc gtf-required gate
    provider = get_provider(provider_name, provider_model)

    declared: dict = {}
    if not isinstance(provider, NullProvider):
        parsed = provider.extract(
            DeclaredFacts,
            system="You extract sequencing metadata from a scientist's request. "
                   "Only use what is stated; use 'unknown' when not stated.",
            prompt=question,
        )
        if parsed is not None:
            declared = parsed.model_dump()

    disagreements = reconcile(declared, measured)
    spec = Spec(
        question=question,
        deliverable=deliverable or question,
        declared=declared,
        measured=measured,
        disagreements=disagreements,
    )
    return {
        "measured": measured,
        "declared": declared,
        "spec": spec.to_dict(),
        "llm_provider": provider.name,
        "llm_model": provider_model,          # the selected model (None = provider default), threaded on
    }
