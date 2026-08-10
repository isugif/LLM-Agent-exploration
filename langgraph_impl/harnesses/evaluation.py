"""Results-evaluation harness (LangGraph node) — SOFT failures (exit == 0).

Parses the tool's output and scores each metric against the expected-range table. Any fail/warn
tier becomes a finding. The LLM is used only to explain anomalies in plain language; the
pass/warn/fail decision itself is deterministic (the expectation table), so the harness cannot be
talked into accepting a bad result.

The scored metrics are DATA — they are the keys of the contract's expectation table, not a
hardcoded list — so a new tool is scored automatically once its contract references an expectation
table and its parser emits those metric names.

Right to refuse: if output can't be parsed, emit status 'cannot_assess' rather than a false 'ok'.
"""

from __future__ import annotations

from shared import contracts_lib as cl
from shared.tools.registry import parse_output
from shared.harness_steps import evaluation_verdict, score_metrics
from shared.llm.provider import provider_by_name, NullProvider


def evaluation_node(state: dict) -> dict:
    tool_id = state["tool"]
    contract = cl.load_contract(tool_id)
    expectations = cl.load_expectations(contract)
    metrics = parse_output(tool_id, state["run_result"]["output_dir"])

    scored, findings = score_metrics(expectations, metrics)

    # LLM explanation is additive only; never changes the deterministic status.
    explanation = None
    # onboarding already resolved the (possibly UI-selected) provider; rebuild by name, no re-check
    provider = provider_by_name(state.get("llm_provider"))
    if findings and not isinstance(provider, NullProvider):
        explanation = provider.complete(
            system=f"You are a bioinformatics QC assistant. Explain flagged {tool_id} metrics briefly "
                   "and note when a flag (e.g. RNA-seq duplication) may be biologically normal.",
            prompt=f"Organism/assay context: {state['spec']['declared']}\nFlagged: {findings}",
        )

    return {"verdict": evaluation_verdict(metrics, scored, findings, explanation).to_dict()}
