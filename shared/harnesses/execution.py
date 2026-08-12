"""Execution harness (framework-neutral) — deterministic compute. No LLM, no judgment.

Uses the generic contract-driven runner (shared.execution.runner.run_tool): the tool's contract
declares how to invoke it, so this is tool-agnostic. In the real system this is where Nextflow
(retries, provenance) would sit.
"""

from __future__ import annotations

import tempfile
from typing import Optional

from shared import contracts_lib as cl
from shared.execution.runner import run_tool


def execute(*, tool: str, fastq: str, out_dir: Optional[str] = None,
            reference: Optional[str] = None, annotation: Optional[str] = None) -> dict:
    """Run the tool via the contract-driven runner. Returns {"run_result": ..., "out_dir": ...}."""
    out_dir = out_dir or tempfile.mkdtemp(prefix=f"{tool}_")
    contract = cl.load_contract(tool)
    inputs = {"reference": reference, "annotation": annotation}
    result = run_tool(contract, fastq, out_dir, inputs=inputs)
    return {"run_result": result.to_dict(), "out_dir": out_dir}
