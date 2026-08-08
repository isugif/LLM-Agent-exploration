"""NOOA-style orchestration: the pipeline as ORDINARY PYTHON control flow.

The validate→fix→revalidate cycle is a plain bounded `while` loop here — the direct contrast with the
LangGraph conditional-edge cycle in langgraph_curator/graph.py. Both call the same stage functions in
curator.stages.steps, so they behave identically; only the orchestration idiom differs.
"""

from __future__ import annotations

from curator.providers.base import Provider
from curator.stages.steps import (
    Outcome, SectionTask, classify, enrich, finalize, fix, transfer, validate,
)


def curate_section(task: SectionTask, providers: dict[str, Provider], max_fixes: int = 2) -> Outcome:
    tool_type = classify(task.source_text)
    obj = transfer(task, providers["transfer"])
    obj = enrich(task, obj, providers["enrich"])

    results = validate(task, obj)
    fixes = 0
    while not finalize(results) and fixes < max_fixes:          # the fix cycle
        failures = [r for r in results if not r.ok]
        obj = fix(task, obj, failures, providers["fix"])
        results = validate(task, obj)
        fixes += 1

    status = "valid" if finalize(results) else "unresolved"
    return Outcome(task.section, status, fixes, obj.model_dump(by_alias=True), results, tool_type)


def curate_tool(tasks: list[SectionTask], providers: dict[str, Provider], max_fixes: int = 2) -> list[Outcome]:
    return [curate_section(t, providers, max_fixes) for t in tasks]
