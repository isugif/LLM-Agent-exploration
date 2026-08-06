"""Onboarding agent (NOOA).

Same harness as langgraph_impl/harnesses/onboarding.py, expressed as a NOOA Agent:
  * `probe_file` / `reconcile` are ordinary (deterministic) methods — normal Python tools.
  * `parse_question` is an agentic method: `@strategy(PredictStrategy())` + a `...` body means the
    LLM fills it in, validated against the DeclaredFacts return type. The docstring is the prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from nooa import Agent, strategy
from nooa.strategies import PredictStrategy

from shared.probes.fastq_probe import probe
from shared.models import Spec


class DeclaredFacts(BaseModel):
    platform: str = Field(description="sequencing platform: illumina, nanopore, pacbio, or unknown")
    assay: str = Field(description="assay type: rna-seq, dna-seq, amplicon, wgs, or unknown")
    layout: str = Field(description="library layout: SE, PE, or unknown")
    organism: str = Field(description="organism if stated, else unknown")


class OnboardingAgent(Agent):
    """You extract sequencing metadata from a scientist's request, using only what is stated."""

    # --- deterministic tools ---
    def probe_file(self, fastq_path: str) -> dict:
        return probe(fastq_path)

    def reconcile(self, question: str, deliverable: str, declared: dict, measured: dict) -> Spec:
        d = []
        dl, ml = (declared.get("layout", "unknown") or "unknown").upper(), measured.get("layout", "")
        if dl == "SE" and ml == "PE?":
            d.append("declared single-end but filename looks like a paired mate (_1/_R1).")
        if dl == "PE" and ml == "SE?":
            d.append("declared paired-end but filename does not look like a mate file.")
        if (declared.get("platform", "unknown") or "").lower() == "nanopore" and \
           measured.get("read_length_max", 0) and measured["read_length_max"] < 200:
            d.append("declared nanopore but reads are short (<200bp), which looks like short-read data.")
        return Spec(question=question, deliverable=deliverable,
                    declared=declared, measured=measured, disagreements=d)

    # --- agentic (LLM-driven) method ---
    @strategy(PredictStrategy())
    async def parse_question(self, question: str) -> DeclaredFacts:
        """Extract the sequencing platform, assay, library layout, and organism the scientist
        states in their request. Use 'unknown' for anything they do not state."""
        ...
