"""Orchestrate the four NOOA agents with ORDINARY PYTHON control flow.

This file is the whole point of the NOOA-vs-LangGraph comparison. Where the LangGraph track needs
a StateGraph with nodes and conditional edges (langgraph_impl/graph.py), here the same routing is
just `if` statements over dataclasses. State lives in local variables and on the agent objects, not
in a shared TypedDict.

Async because NOOA agentic methods are awaited. Degrades gracefully: if the LLM is unavailable, the
LLM-driven steps are skipped and the deterministic checks still run.
"""

from __future__ import annotations

import tempfile

from shared import contracts_lib as cl
from shared.execution.runner import run_tool
from shared.models import RouteDecision, Verdict

from nooa_impl.llm import build_llm
from nooa_impl.agents.onboarding import OnboardingAgent
from nooa_impl.agents.judgment import JudgmentAgent
from nooa_impl.agents.diagnosis import DiagnosisAgent
from nooa_impl.agents.evaluation import EvaluationAgent


async def run_pipeline(fastq: str, question: str, deliverable: str | None = None,
                       out_dir: str | None = None, tool_id: str = "fastqc") -> dict:
    deliverable = deliverable or question
    llm, have_llm, provider_name = build_llm()

    # All agents get the (lazily-constructed) llm so they build even when Ollama is down;
    # `have_llm` gates whether we actually CALL the agentic methods. Each judging agent loads the
    # contract for `tool_id` — so the pipeline is tool-agnostic.
    onboard = OnboardingAgent(llm=llm)
    judge = JudgmentAgent(tool_id, llm=llm)
    diagnose = DiagnosisAgent(tool_id, llm=llm)
    evaluate = EvaluationAgent(tool_id, llm=llm)

    report: dict = {"track": "nooa", "tool": tool_id, "llm_provider": provider_name}

    # --- 1. Onboarding -------------------------------------------------------
    measured = onboard.probe_file(fastq, tool_id)
    declared: dict = {}
    if have_llm:
        declared = (await onboard.parse_question(question)).model_dump()
    spec = onboard.reconcile(question, deliverable, declared, measured)
    report["spec"] = spec.to_dict()

    # --- 2. Judgment (fit critic) -------------------------------------------
    blocking, warnings = judge.check_preconditions(spec.declared, spec.measured)
    confirmed, boundary_notes = [], []
    tool_summary = (judge.contract.get("summary") or "").strip()
    for b in judge.candidate_boundaries(deliverable):
        if have_llm:
            res = await judge.confirm_boundary(tool_id, tool_summary, b["boundary"], deliverable)
            boundary_notes.append(f"{b['id']}: {res.reason}")
            if res.violates:
                confirmed.append(b["id"])
        else:
            # same degradation rule as the LangGraph NullProvider: do not auto-refuse on a keyword hit
            boundary_notes.append(f"potential boundary '{b['id']}' not confirmed (no LLM); allowed with warning")
    route: RouteDecision = judge.route(blocking, confirmed, boundary_notes, warnings)
    report["route"] = route.to_dict()

    if route.action == "refuse":
        report["run_result"] = None
        report["verdict"] = None
        return report

    # --- 3. Execution --------------------------------------------------------
    out_dir = out_dir or tempfile.mkdtemp(prefix=f"{tool_id}_")
    report["out_dir"] = out_dir
    run_result = run_tool(cl.load_contract(tool_id), fastq, out_dir)
    report["run_result"] = {k: v for k, v in run_result.to_dict().items()
                            if k not in ("stdout", "stderr")}

    # --- 4. Diagnosis (crash) | Evaluation (implausible output) -------------
    if not run_result.ok:
        verdict: Verdict = diagnose.diagnose(run_result)
    else:
        metrics = evaluate.parse(run_result.output_dir)
        scored, findings = evaluate.score(metrics)
        explanation = None
        if findings and have_llm:
            explanation = (await evaluate.explain(spec.declared, findings)).explanation
        verdict = evaluate.verdict(metrics, scored, findings, explanation)
    report["verdict"] = verdict.to_dict()
    return report
