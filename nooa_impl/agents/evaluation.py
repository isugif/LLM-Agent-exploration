"""Results-evaluation agent (NOOA) — SOFT failures.

Mirrors langgraph_impl/harnesses/evaluation.py. Deterministic scoring against the expectation
table decides the tier; the agentic `explain` method only adds a plain-language note and never
changes the tier. Refuses (`cannot_assess`) when output is unparseable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from nooa import Agent, strategy
from nooa.strategies import PredictStrategy

from shared import contracts_lib as cl
from shared.tools.registry import get_parser
from shared.models import Verdict


class Explanation(BaseModel):
    explanation: str = Field(description="brief plain-language explanation of the flagged metrics")


class EvaluationAgent(Agent):
    """You judge whether a tool's output is biologically reasonable by comparing metrics to expected
    ranges, and you note when a flag (e.g. RNA-seq duplication) may be biologically normal."""

    def __init__(self, tool_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_id = tool_id
        self.contract = cl.load_contract(tool_id)
        self.expectations = cl.load_expectations(self.contract)

    # --- deterministic tools ---
    def parse(self, output_dir: str) -> dict:
        return get_parser(self.tool_id)(output_dir)

    def score(self, metrics: dict):
        scored, findings = {}, []
        for name in self.expectations.get("metrics", {}):   # scored metrics come from the contract
            if name in metrics:
                s = cl.score_metric(self.expectations, name, metrics[name])
                scored[name] = s
                if s["tier"] in ("warn", "fail"):
                    note = f" ({s['note']})" if s["note"] else ""
                    findings.append(f"{name}={s['value']} -> {s['tier'].upper()}{note}")
        return scored, findings

    def verdict(self, metrics: dict, scored: dict, findings: list, explanation: str | None) -> Verdict:
        if "error" in metrics:
            return Verdict(status="cannot_assess", findings=[metrics["error"]], escalate=True)
        f = list(findings)
        if explanation:
            f.append(f"explanation: {explanation}")
        return Verdict(status="ok" if not findings else "anomaly",
                       findings=f or ["all scored metrics within expected ranges"],
                       metrics=scored, escalate=False)

    # --- agentic (LLM-driven) method ---
    @strategy(PredictStrategy())
    async def explain(self, context: dict, findings: list) -> Explanation:
        """Explain the flagged FastQC metrics briefly for the given organism/assay context, and
        note when a flag may be biologically normal (e.g. high duplication in RNA-seq)."""
        ...
