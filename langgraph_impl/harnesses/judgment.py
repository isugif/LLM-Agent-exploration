"""Judgment harness (LangGraph node) — thin adapter over shared.harnesses.judgment.

The fit-critic logic (HRR review gate, deterministic preconditions, LLM-confirmed boundaries) lives
in shared/harnesses/judgment.py, single-sourced with the MCP order-guard. This node only unpacks the
LangGraph state dict.
"""

from __future__ import annotations

from shared.harnesses.judgment import BoundaryCheck, judge   # noqa: F401 (re-export)


def judgment_node(state: dict) -> dict:
    return judge(tool=state["tool"], spec=state["spec"], llm_provider=state.get("llm_provider"),
                 llm_model=state.get("llm_model"))
