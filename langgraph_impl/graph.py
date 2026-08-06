"""Wire the four harnesses into a LangGraph StateGraph.

The graph IS the orchestration. Routing lives in conditional edges the developer authors:

    onboarding -> judgment -> (refuse? END : execute)
                              execute -> (exit!=0? diagnosis : evaluation) -> END

This is the defining contrast with the NOOA track, where the same control flow is ordinary
Python `if` statements in orchestrator.py.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from langgraph_impl.state import PipelineState
from langgraph_impl.harnesses.onboarding import onboarding_node
from langgraph_impl.harnesses.judgment import judgment_node
from langgraph_impl.harnesses.execution import execution_node
from langgraph_impl.harnesses.diagnosis import diagnosis_node
from langgraph_impl.harnesses.evaluation import evaluation_node


def _after_judgment(state: PipelineState) -> str:
    return "execute" if state["route"]["action"] == "run" else END


def _after_execution(state: PipelineState) -> str:
    return "evaluation" if state["run_result"]["ok"] else "diagnosis"


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("onboarding", onboarding_node)
    g.add_node("judgment", judgment_node)
    g.add_node("execute", execution_node)
    g.add_node("diagnosis", diagnosis_node)
    g.add_node("evaluation", evaluation_node)

    g.add_edge(START, "onboarding")
    g.add_edge("onboarding", "judgment")
    g.add_conditional_edges("judgment", _after_judgment, {"execute": "execute", END: END})
    g.add_conditional_edges("execute", _after_execution,
                            {"evaluation": "evaluation", "diagnosis": "diagnosis"})
    g.add_edge("evaluation", END)
    g.add_edge("diagnosis", END)
    return g.compile()
