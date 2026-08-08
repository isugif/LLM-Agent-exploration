"""LangGraph orchestration: the pipeline as a StateGraph with a validate→fix CYCLE.

The headline of the whole exercise: the skill's `iterate R2..R4 until clean` loop — which the text
skill had to self-enforce — is here a single conditional edge (`validate` → `fix` → back to
`validate`, or → `finalize`). Node bodies just call the shared stage functions.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from curator.providers.base import Provider
from curator.stages.steps import (
    Outcome, SectionTask, classify, enrich, finalize, fix, transfer, validate,
)


class CuratorState(TypedDict, total=False):
    task: SectionTask
    providers: dict[str, Provider]
    max_fixes: int
    tool_type: str
    obj: Any            # the pydantic section object (held in-memory)
    results: list       # list[CheckResult]
    fixes: int
    status: str


def _classify(s: CuratorState) -> dict:
    return {"tool_type": classify(s["task"].source_text), "fixes": 0}


def _transfer(s: CuratorState) -> dict:
    return {"obj": transfer(s["task"], s["providers"]["transfer"])}


def _enrich(s: CuratorState) -> dict:
    return {"obj": enrich(s["task"], s["obj"], s["providers"]["enrich"])}


def _validate(s: CuratorState) -> dict:
    return {"results": validate(s["task"], s["obj"])}


def _fix(s: CuratorState) -> dict:
    failures = [r for r in s["results"] if not r.ok]
    return {"obj": fix(s["task"], s["obj"], failures, s["providers"]["fix"]),
            "fixes": s.get("fixes", 0) + 1}


def _finalize(s: CuratorState) -> dict:
    return {"status": "valid" if finalize(s["results"]) else "unresolved"}


def _after_validate(s: CuratorState) -> str:
    if finalize(s["results"]):
        return "finalize"
    return "fix" if s.get("fixes", 0) < s.get("max_fixes", 2) else "finalize"


def build_graph():
    g = StateGraph(CuratorState)
    g.add_node("classify", _classify)
    g.add_node("transfer", _transfer)
    g.add_node("enrich", _enrich)
    g.add_node("validate", _validate)
    g.add_node("fix", _fix)
    g.add_node("finalize", _finalize)

    g.add_edge(START, "classify")
    g.add_edge("classify", "transfer")
    g.add_edge("transfer", "enrich")
    g.add_edge("enrich", "validate")
    g.add_conditional_edges("validate", _after_validate, {"fix": "fix", "finalize": "finalize"})
    g.add_edge("fix", "validate")          # the cycle
    g.add_edge("finalize", END)
    return g.compile()


def curate_section(task: SectionTask, providers: dict[str, Provider], max_fixes: int = 2) -> Outcome:
    final = build_graph().invoke(
        {"task": task, "providers": providers, "max_fixes": max_fixes})
    obj = final.get("obj")
    return Outcome(task.section, final.get("status", "unresolved"), final.get("fixes", 0),
                   obj.model_dump(by_alias=True) if obj is not None else None,
                   final.get("results", []), final.get("tool_type"))


def curate_tool(tasks: list[SectionTask], providers: dict[str, Provider], max_fixes: int = 2) -> list[Outcome]:
    return [curate_section(t, providers, max_fixes) for t in tasks]
