"""Results-evaluation harness (LangGraph node) — SOFT failures (exit == 0).

Parses FastQC output and scores each metric against the expected-range table. Any fail/warn tier
becomes a finding. The LLM is used only to explain anomalies in plain language; the pass/warn/fail
decision itself is deterministic (the expectation table), so the harness cannot be talked into
accepting a bad result.

Right to refuse: if output can't be parsed, emit status 'cannot_assess' rather than a false 'ok'.
"""

from __future__ import annotations

from shared import contracts_lib as cl
from shared.qc.fastqc_parse import parse_fastqc
from shared.models import Verdict
from shared.llm.provider import get_provider, NullProvider

SCORED = [
    "per_base_mean_quality", "percent_gc", "percent_duplication",
    "overrepresented_percent", "adapter_content_max_percent",
]


def evaluation_node(state: dict) -> dict:
    contract = cl.load_contract("fastqc")
    expectations = cl.load_expectations(contract)
    metrics = parse_fastqc(state["run_result"]["output_dir"])

    if "error" in metrics:
        return {"verdict": Verdict(
            status="cannot_assess",
            findings=[metrics["error"]],
            escalate=True,
        ).to_dict()}

    scored, findings = {}, []
    for name in SCORED:
        if name in metrics:
            s = cl.score_metric(expectations, name, metrics[name])
            scored[name] = s
            if s["tier"] in ("warn", "fail"):
                note = f" ({s['note']})" if s["note"] else ""
                findings.append(f"{name}={s['value']} -> {s['tier'].upper()}{note}")

    status = "ok" if not findings else "anomaly"

    # LLM explanation is additive only; never changes the deterministic status.
    explanation = None
    provider = get_provider()
    if findings and not isinstance(provider, NullProvider):
        explanation = provider.complete(
            system="You are a bioinformatics QC assistant. Explain flagged FastQC metrics briefly "
                   "and note when a flag (e.g. RNA-seq duplication) may be biologically normal.",
            prompt=f"Organism/assay context: {state['spec']['declared']}\nFlagged: {findings}",
        )
    if explanation:
        findings.append(f"explanation: {explanation}")

    return {"verdict": Verdict(
        status=status,
        findings=findings or ["all scored metrics within expected ranges"],
        metrics=scored,
        escalate=False,
    ).to_dict()}
