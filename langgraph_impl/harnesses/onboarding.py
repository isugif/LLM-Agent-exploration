"""Onboarding harness (LangGraph node).

Produces the structured spec by reconciling DECLARED facts (parsed from the question by the LLM)
against MEASURED facts (probed from the file). Disagreements are recorded, not silently resolved.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from shared.tools.registry import get_probe
from shared.models import Spec
from shared.llm.provider import get_provider, NullProvider


class DeclaredFacts(BaseModel):
    """What the scientist asserts about their data (LLM-extracted from the question)."""
    platform: str = Field(description="sequencing platform: illumina, nanopore, pacbio, or unknown")
    assay: str = Field(description="assay type: rna-seq, dna-seq, amplicon, wgs, or unknown")
    layout: str = Field(description="library layout: SE, PE, or unknown")
    organism: str = Field(description="organism if stated, else unknown")


def _reconcile(declared: dict, measured: dict) -> list[str]:
    """Flag declared-vs-measured conflicts — the cheap silent-error catch."""
    d = []
    dl, ml = declared.get("layout", "unknown").upper(), measured.get("layout", "")
    if dl == "SE" and ml == "PE?":
        d.append("declared single-end but filename looks like a paired mate (_1/_R1).")
    if dl == "PE" and ml == "SE?":
        d.append("declared paired-end but filename does not look like a mate file.")
    if declared.get("platform", "unknown").lower() == "nanopore" and \
       measured.get("read_length_max", 0) and measured["read_length_max"] < 200:
        d.append("declared nanopore but reads are short (<200bp), which looks like short-read data.")
    return d


def onboarding_node(state: dict) -> dict:
    measured = get_probe(state["tool"])(state["fastq"])
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

    disagreements = _reconcile(declared, measured)
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
