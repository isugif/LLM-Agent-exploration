"""Diagnosis agent (NOOA) — HARD failures. Fully deterministic (the crash has ground truth).

Mirrors langgraph_impl/harnesses/diagnosis.py. No agentic methods: matching a crash signal to the
contract's failure_modes needs no LLM.
"""

from __future__ import annotations

from nooa import Agent

from shared import contracts_lib as cl
from shared.harness_steps import diagnose_run
from shared.models import RunResult, Verdict


class DiagnosisAgent(Agent):
    """You match a failed run's audit trail against known failure modes and propose the fix."""

    def __init__(self, tool_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = cl.load_contract(tool_id)

    def diagnose(self, run_result: RunResult) -> Verdict:
        return diagnose_run(
            self.contract,
            stdout=run_result.stdout, stderr=run_result.stderr,
            error=run_result.error, exit_code=run_result.exit_code,
        )
