"""Diagnosis harness (framework-neutral) — HARD failures (exit != 0).

Reads the audit trail (stderr/stdout/error) and matches it against the contract's failure_modes
signals. A match yields a known fix; no match escalates to human curation. This is deterministic
pattern-matching over the incident library — the crash has ground truth, so no LLM is required.
"""

from __future__ import annotations

from shared import contracts_lib as cl
from shared.harness_steps import diagnose_run


def diagnose(*, tool: str, run_result: dict) -> dict:
    """Match a failed run against the contract's failure_modes. Returns {"verdict": Verdict.to_dict()}."""
    contract = cl.load_contract(tool)
    return {"verdict": diagnose_run(
        contract,
        stdout=run_result.get("stdout"), stderr=run_result.get("stderr"),
        error=run_result.get("error"), exit_code=run_result.get("exit_code"),
    ).to_dict()}
