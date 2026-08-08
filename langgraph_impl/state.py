"""Shared state for the LangGraph pipeline.

In LangGraph, state is an explicit TypedDict that flows through every node. Each node returns a
partial dict that LangGraph merges into the running state. This is the defining contrast with the
NOOA track, where state lives as fields on an agent object. Same information, different home.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    # inputs
    tool: str                          # which tool's contract to route against (e.g. "fastqc")
    fastq: str                         # input path (a FASTQ file, or a report dir for aggregators)
    question: str
    deliverable: str
    out_dir: str
    provider: str                      # LLM provider for this run: "ollama" | "claude" | "auto"/absent

    # onboarding
    declared: dict[str, Any]
    measured: dict[str, Any]
    spec: dict[str, Any]

    # judgment
    route: dict[str, Any]              # RouteDecision.to_dict()

    # execution
    run_result: dict[str, Any]         # RunResult.to_dict()

    # diagnosis / evaluation
    verdict: dict[str, Any]            # Verdict.to_dict()

    # bookkeeping
    llm_provider: str                  # "ollama" | "null"
    errors: list[str]
