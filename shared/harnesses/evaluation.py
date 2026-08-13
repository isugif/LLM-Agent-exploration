"""Results-evaluation harness (framework-neutral) — SOFT failures (exit == 0).

Parses the tool's output and scores each metric against the expected-range table. Any fail/warn
tier becomes a finding. The LLM is used only to explain anomalies in plain language; the
pass/warn/fail decision itself is deterministic (the expectation table), so the harness cannot be
talked into accepting a bad result.

Right to refuse: if output can't be parsed, emit status 'cannot_assess' rather than a false 'ok'.
"""

from __future__ import annotations

from typing import Optional

from shared import contracts_lib as cl
from shared.tools.registry import parse_output
from shared.harness_steps import evaluation_verdict, score_metrics
from shared.llm.provider import provider_by_name, NullProvider


def evaluate(*, tool: str, run_result: dict, spec: dict, llm_provider: Optional[str] = None,
             llm_model: Optional[str] = None) -> dict:
    """Score the run's output against expectations. Returns {"verdict": Verdict.to_dict()}."""
    contract = cl.load_contract(tool)
    expectations = cl.load_expectations(contract)
    metrics = parse_output(tool, run_result["output_dir"])

    scored, findings = score_metrics(expectations, metrics)

    # LLM explanation is additive only; never changes the deterministic status.
    explanation = None
    provider = provider_by_name(llm_provider, llm_model)
    if findings and not isinstance(provider, NullProvider):
        explanation = provider.complete(
            system=f"You are a bioinformatics QC assistant. Explain flagged {tool} metrics briefly "
                   "and note when a flag (e.g. RNA-seq duplication) may be biologically normal.",
            prompt=f"Organism/assay context: {spec['declared']}\nFlagged: {findings}",
        )

    return {"verdict": evaluation_verdict(metrics, scored, findings, explanation).to_dict()}
