"""Diagnosis agent (NOOA) — HARD failures. Fully deterministic (the crash has ground truth).

Mirrors langgraph_impl/harnesses/diagnosis.py. No agentic methods: matching a crash signal to the
contract's failure_modes needs no LLM.
"""

from __future__ import annotations

from nooa import Agent

from shared import contracts_lib as cl
from shared.models import RunResult, Verdict


class DiagnosisAgent(Agent):
    """You match a failed run's audit trail against known failure modes and propose the fix."""

    def __init__(self, tool_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = cl.load_contract(tool_id)

    def diagnose(self, run_result: RunResult) -> Verdict:
        haystack = "\n".join([run_result.stderr or "", run_result.stdout or "", run_result.error or ""])
        for fm in self.contract.get("failure_modes", []):
            if fm["signal"].lower() in haystack.lower():
                return Verdict(
                    status="failure",
                    findings=[f"matched failure mode '{fm['id']}' (signal: {fm['signal']!r})"],
                    proposed_fix=fm["fix"], escalate=False,
                )
        if run_result.error and "not found on PATH" in run_result.error:
            tool = self.contract["id"]
            hint = self.contract.get("execution", {}).get("install_hint", "")
            return Verdict(status="failure", findings=[f"{tool} is not installed"],
                           proposed_fix=f"Install {tool}: `{hint}`.", escalate=False)
        return Verdict(
            status="failure",
            findings=[f"unrecognized failure (exit={run_result.exit_code}). stderr tail: "
                      + (run_result.stderr or "")[-300:]],
            proposed_fix=None, escalate=True,   # novel crash -> human curation
        )
