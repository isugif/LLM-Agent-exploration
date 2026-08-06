"""Diagnosis harness (LangGraph node) — HARD failures (exit != 0).

Reads the audit trail (stderr/stdout/error) and matches it against the contract's failure_modes
signals. A match yields a known fix; no match escalates to human curation. This is deterministic
pattern-matching over the incident library — the crash has ground truth, so no LLM is required.
"""

from __future__ import annotations

from shared import contracts_lib as cl
from shared.models import Verdict


def diagnosis_node(state: dict) -> dict:
    contract = cl.load_contract("fastqc")
    rr = state["run_result"]
    haystack = "\n".join([rr.get("stderr") or "", rr.get("stdout") or "", rr.get("error") or ""])

    for fm in contract.get("failure_modes", []):
        if fm["signal"].lower() in haystack.lower():
            return {"verdict": Verdict(
                status="failure",
                findings=[f"matched failure mode '{fm['id']}' (signal: {fm['signal']!r})"],
                proposed_fix=fm["fix"],
                escalate=False,
            ).to_dict()}

    # tool-not-installed is its own known condition
    if rr.get("error") and "not found on PATH" in rr["error"]:
        return {"verdict": Verdict(
            status="failure",
            findings=["fastqc is not installed"],
            proposed_fix="Install FastQC: `mamba install -c bioconda fastqc`.",
            escalate=False,
        ).to_dict()}

    return {"verdict": Verdict(
        status="failure",
        findings=[f"unrecognized failure (exit={rr.get('exit_code')}). stderr tail: "
                  + (rr.get("stderr") or "")[-300:]],
        proposed_fix=None,
        escalate=True,      # novel crash -> human curation -> becomes a new failure_mode entry
    ).to_dict()}
