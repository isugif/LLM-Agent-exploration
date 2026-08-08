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
from shared.tools.registry import get_parser
from shared.models import Verdict
from shared.llm.provider import get_provider, NullProvider


def evaluation_node(state: dict) -> dict:
    tool_id = state["tool"]
    contract = cl.load_contract(tool_id)
    expectations = cl.load_expectations(contract)
    metrics = get_parser(tool_id)(state["run_result"]["output_dir"])

    if "error" in metrics:
        return {"verdict": Verdict(
            status="cannot_assess",
            findings=[metrics["error"]],
            escalate=True,
        ).to_dict()}

    scored, findings = {}, []
    for name in expectations.get("metrics", {}):        # scored metrics come from the contract
        if name in metrics:
            s = cl.score_metric(expectations, name, metrics[name])
            scored[name] = s
            if s["tier"] in ("warn", "fail"):
                note = f" ({s['note']})" if s["note"] else ""
                findings.append(f"{name}={s['value']} -> {s['tier'].upper()}{note}")

    status = "ok" if not findings else "anomaly"

    # LLM explanation is additive only; never changes the deterministic status.
    explanation = None
    provider = get_provider(state.get("provider"))
    if findings and not isinstance(provider, NullProvider):
        explanation = provider.complete(
            system=f"You are a bioinformatics QC assistant. Explain flagged {tool_id} metrics briefly "
                   "and note when a flag (e.g. RNA-seq duplication) may be biologically normal.",
            prompt=f"Organism/assay context: {state['spec']['declared']}\nFlagged: {findings}",
        )

    return {"verdict": Verdict(
        status=status,
        findings=findings or ["all scored metrics within expected ranges"],
        explanation=explanation,
        metrics=scored,
        escalate=False,
    ).to_dict()}
