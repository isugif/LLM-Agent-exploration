"""Execution node (LangGraph) — thin adapter over shared.harnesses.execution.

Contract-driven compute lives in shared/harnesses/execution.py (single source shared with the MCP
order-guard). No LLM, no judgment.
"""

from __future__ import annotations

from shared.harnesses.execution import execute


def execution_node(state: dict) -> dict:
    return execute(
        tool=state["tool"],
        fastq=state["fastq"],
        out_dir=state.get("out_dir"),
        reference=state.get("reference"),
        annotation=state.get("annotation"),
    )
