"""Results-evaluation harness (LangGraph node) — thin adapter over shared.harnesses.evaluation.

SOFT failures (exit == 0): parse output, score metrics against the expectation table, refuse with
'cannot_assess' when output can't be parsed. Logic single-sourced in shared/harnesses/evaluation.py.
"""

from __future__ import annotations

from shared.harnesses.evaluation import evaluate


def evaluation_node(state: dict) -> dict:
    return evaluate(
        tool=state["tool"],
        run_result=state["run_result"],
        spec=state["spec"],
        llm_provider=state.get("llm_provider"),
    )
