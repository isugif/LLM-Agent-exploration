"""The order-guard: the four harnesses sequenced explicitly, framework-free.

This is the single, explicit source of the harness ORDER invariant

    onboarding -> judgment -> (refuse? stop : execute)
                             execute -> (exit!=0? diagnosis : evaluation)

that, until now, existed only *emergently* — as LangGraph conditional edges
(langgraph_impl/graph.py) or as top-to-bottom statement order (nooa_impl/orchestrator.py). The MCP
`run_tool` calls this, so the refusal gate is server-enforced, not advisory: a caller cannot skip
onboarding or judgment, and refuse short-circuits *before any compute*.

The per-checkpoint logic is single-sourced in shared/harnesses/* (the same functions the LangGraph
nodes now delegate to), so this sequencer adds ordering only — no duplicated harness behavior. It
runs its full deterministic half with no LLM reachable (graceful degradation via NullProvider).
"""

from __future__ import annotations

from typing import Optional

from shared.harnesses.onboarding import onboard
from shared.harnesses.judgment import judge
from shared.harnesses.execution import execute
from shared.harnesses.evaluation import evaluate
from shared.harnesses.diagnosis import diagnose


def run_pipeline(*, tool: str, fastq: str, question: Optional[str] = None,
                 deliverable: Optional[str] = None, reference: Optional[str] = None,
                 annotation: Optional[str] = None, out_dir: Optional[str] = None,
                 provider: Optional[str] = None, provider_model: Optional[str] = None,
                 declared: Optional[dict] = None) -> dict:
    """Run onboard -> judge -> (refuse | run -> evaluate | diagnose) and return the full trace.

    Returns a dict with: spec, route, run_result, verdict, out_dir, measured, declared,
    llm_provider, and `trace` (the ordered list of checkpoints actually visited). `run_result` and
    `verdict` are None when judgment refuses before compute.
    """
    question = question or f"run {tool} on {fastq}"
    result: dict = {"run_result": None, "verdict": None, "out_dir": out_dir}
    trace: list[str] = []

    # 1) onboarding — probe + declared/measured reconciliation
    ob = onboard(tool=tool, fastq=fastq, question=question, deliverable=deliverable,
                 reference=reference, annotation=annotation, provider_name=provider,
                 provider_model=provider_model, declared=declared)
    result.update(ob)
    trace.append("onboarding")

    # 2) judgment — right to refuse before any compute
    jd = judge(tool=tool, spec=ob["spec"], llm_provider=ob["llm_provider"], llm_model=ob["llm_model"])
    result.update(jd)
    trace.append("judgment")
    if jd["route"]["action"] != "run":
        result["trace"] = trace + ["refused"]
        return result

    # 3) execution — deterministic compute
    ex = execute(tool=tool, fastq=fastq, out_dir=out_dir, reference=reference, annotation=annotation)
    result.update(ex)
    trace.append("execution")

    # 4) evaluation (exit == 0) | diagnosis (exit != 0)
    if ex["run_result"]["ok"]:
        result.update(evaluate(tool=tool, run_result=ex["run_result"], spec=ob["spec"],
                               llm_provider=ob["llm_provider"], llm_model=ob["llm_model"]))
        trace.append("evaluation")
    else:
        result.update(diagnose(tool=tool, run_result=ex["run_result"]))
        trace.append("diagnosis")

    result["trace"] = trace
    return result
