"""Execution node (LangGraph) — deterministic compute. No LLM, no judgment.

Thin wrapper over shared.execution.fastqc_runner so the graph has a node to own the run and its
audit record. In the real system this is where Nextflow (retries, provenance) would sit.
"""

from __future__ import annotations

import os
import tempfile

from shared.execution.fastqc_runner import run_fastqc


def execution_node(state: dict) -> dict:
    out_dir = state.get("out_dir") or tempfile.mkdtemp(prefix="fastqc_")
    result = run_fastqc(state["fastq"], out_dir)
    return {"run_result": result.to_dict(), "out_dir": out_dir}
