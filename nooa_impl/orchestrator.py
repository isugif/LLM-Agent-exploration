"""Orchestrate the four NOOA agents with ORDINARY PYTHON control flow.

This file is the whole point of the NOOA-vs-LangGraph comparison. Where the LangGraph track needs
a StateGraph with nodes and conditional edges (langgraph_impl/graph.py), here the same routing is
just `if` statements over dataclasses. State lives in local variables and on the agent objects, not
in a shared TypedDict.

Async because NOOA agentic methods are awaited. Degrades gracefully: if the LLM is unavailable, the
LLM-driven steps are skipped and the deterministic checks still run.
"""

from __future__ import annotations

import os
import tempfile

from shared.execution.fastqc_runner import run_fastqc
from shared.models import RouteDecision, Verdict

from nooa_impl.llm import build_llm
from nooa_impl.agents.onboarding import OnboardingAgent
from nooa_impl.agents.judgment import JudgmentAgent
from nooa_impl.agents.diagnosis import DiagnosisAgent
from nooa_impl.agents.evaluation import EvaluationAgent


async def run_pipeline(fastq: str, question: str, deliverable: str | None = None,
                       out_dir: str | None = None) -> dict:
    deliverable = deliverable or question
    llm, have_llm, provider_name = build_llm()

    # All agents get the (lazily-constructed) llm so they build even when Ollama is down;
    # `have_llm` gates whether we actually CALL the agentic methods.
    onboard = OnboardingAgent(llm=llm)
    judge = JudgmentAgent(llm=llm)
    diagnose = DiagnosisAgent(llm=llm)
    evaluate = EvaluationAgent(llm=llm)

    report: dict = {"track": "nooa", "llm_provider": provider_name}

    # --- 1. Onboarding -------------------------------------------------------
    measured = onboard.probe_file(fastq)
    declared: dict = {}
    if have_llm:
        declared = (await onboard.parse_question(question)).model_dump()
    spec = onboard.reconcile(question, deliverable, declared, measured)
    report["spec"] = spec.to_dict()

    # --- 2. Judgment (fit critic) -------------------------------------------
    blocking, warnings = judge.check_preconditions(spec.declared, spec.measured)
    confirmed, boundary_notes = [], []
    for b in judge.candidate_boundaries(deliverable):
        if have_llm:
            res = await judge.confirm_boundary(b["boundary"], deliverable)
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
    out_dir = out_dir or tempfile.mkdtemp(prefix="fastqc_")
    run_result = run_fastqc(fastq, out_dir)
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
