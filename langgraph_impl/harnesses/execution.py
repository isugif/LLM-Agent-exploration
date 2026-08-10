"""Execution node (LangGraph) — deterministic compute. No LLM, no judgment.

Uses the generic contract-driven runner (shared.execution.runner.run_tool): the tool's contract.yml
declares how to invoke it, so this node is tool-agnostic. In the real system this is where Nextflow
(retries, provenance) would sit.
"""

from __future__ import annotations

import tempfile

from shared import contracts_lib as cl
from shared.execution.runner import run_tool


def execution_node(state: dict) -> dict:
    out_dir = state.get("out_dir") or tempfile.mkdtemp(prefix=f"{state['tool']}_")
    contract = cl.load_contract(state["tool"])
    result = run_tool(contract, state["fastq"], out_dir, reference=state.get("reference"))
    return {"run_result": result.to_dict(), "out_dir": out_dir}
