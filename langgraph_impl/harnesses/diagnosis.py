"""Diagnosis harness (LangGraph node) — HARD failures (exit != 0).

Reads the audit trail (stderr/stdout/error) and matches it against the contract's failure_modes
signals. A match yields a known fix; no match escalates to human curation. This is deterministic
pattern-matching over the incident library — the crash has ground truth, so no LLM is required.
"""

from __future__ import annotations

from shared import contracts_lib as cl
from shared.harness_steps import diagnose_run


def diagnosis_node(state: dict) -> dict:
    contract = cl.load_contract(state["tool"])
    rr = state["run_result"]
    return {"verdict": diagnose_run(
        contract,
        stdout=rr.get("stdout"), stderr=rr.get("stderr"),
        error=rr.get("error"), exit_code=rr.get("exit_code"),
    ).to_dict()}
