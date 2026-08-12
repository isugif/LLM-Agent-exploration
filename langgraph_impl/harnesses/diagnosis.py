"""Diagnosis harness (LangGraph node) — thin adapter over shared.harnesses.diagnosis.

HARD failures (exit != 0): match the audit trail against the contract's failure_modes; novel crashes
escalate to human curation. Deterministic; logic single-sourced in shared/harnesses/diagnosis.py.
"""

from __future__ import annotations

from shared.harnesses.diagnosis import diagnose


def diagnosis_node(state: dict) -> dict:
    return diagnose(tool=state["tool"], run_result=state["run_result"])
