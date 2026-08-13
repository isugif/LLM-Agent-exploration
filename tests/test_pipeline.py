"""Tests for the order-guard sequencer (shared/pipeline.py).

These assert the ORDER invariant the MCP `run_tool` relies on: judgment can refuse before any
compute, and a successful run routes to evaluation while a failed run routes to diagnosis. Runs in
deterministic mode (Ollama forced unreachable -> NullProvider); the branch tests monkeypatch
`execute` so they need no external tool binary.

Run: conda run -n nooa python -m pytest tests/test_pipeline.py -q
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

import pytest

os.environ["OLLAMA_HOST"] = "http://localhost:1"     # force deterministic (NullProvider)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared import pipeline                            # noqa: E402
from shared.models import RunResult                    # noqa: E402

GOOD = str(REPO / "tests/inputs/good.fastq.gz")


# --- refuse before compute -----------------------------------------------------

def test_run_pipeline_reuses_declared_facts():
    """Passing `declared` skips onboarding's LLM extraction and carries the reused facts into the
    spec — the batch cost-saver's plumbing."""
    r = pipeline.run_pipeline(tool="minimap2", fastq=GOOD, reference=None, question="align",
                              declared={"platform": "nanopore", "assay": "dna-seq",
                                        "layout": "SE", "organism": "yeast"})
    assert r["declared"]["assay"] == "dna-seq"
    assert r["spec"]["declared"]["platform"] == "nanopore"


def test_runnable_gate_refuses_a_documented_only_contract():
    """A documented-for-explain/find-only tool (no machine execution section) refuses at judgment with
    `not_runnable`; a contract with argv OR steps passes the gate."""
    from shared.harness_steps import runnable_gate
    assert runnable_gate({"id": "aligner", "execution": {"steps": [["hisat2"]]}}) is None   # steps -> ok
    assert runnable_gate({"id": "aligner", "execution": {"argv": ["fastqc"]}}) is None       # argv  -> ok
    r = runnable_gate({"id": "docsonly", "execution": {}})                                   # neither -> refuse
    assert r.action == "refuse" and any("not_runnable" in f for f in r.precondition_failures)


def test_hisat2_multistep_is_now_runnable():
    """hisat2 (a two-step build+align contract) is no longer 'not runnable' — it refuses only on the
    missing reference precondition, proving the multi-step execution wired it into the harness."""
    r = pipeline.run_pipeline(tool="hisat2", fastq=GOOD, reference=None, question="align these reads")
    assert r["route"]["action"] == "refuse"
    fails = r["route"]["precondition_failures"]
    assert any("reference_provided" in f for f in fails)
    assert not any("not_runnable" in f for f in fails)   # it IS runnable now, just needs a reference


def test_refuse_short_circuits_before_compute():
    """minimap2 with no reference must refuse in judgment and never reach execution."""
    r = pipeline.run_pipeline(tool="minimap2", fastq=GOOD, reference=None,
                              question="align these reads")
    assert r["route"]["action"] == "refuse"
    assert any("reference_provided" in f for f in r["route"]["precondition_failures"])
    assert r["run_result"] is None and r["verdict"] is None
    assert r["trace"] == ["onboarding", "judgment", "refused"]
    assert "execution" not in r["trace"]


# --- run -> (evaluate | diagnose) branch (monkeypatched execute, no binary needed) -------------

def _run_result(*, ok: bool, output_dir: str = "/tmp") -> dict:
    return RunResult(tool="fastqc", ok=ok, exit_code=0 if ok else 1, stdout="",
                     stderr="" if ok else "segfault", output_dir=output_dir if ok else None,
                     audit={}, error=None if ok else "boom").to_dict()


def test_ok_run_routes_to_evaluation(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "execute",
                        lambda **kw: {"run_result": _run_result(ok=True, output_dir=str(tmp_path)),
                                      "out_dir": str(tmp_path)})
    r = pipeline.run_pipeline(tool="fastqc", fastq=GOOD, question="qc these reads")
    assert r["route"]["action"] == "run"
    assert r["trace"] == ["onboarding", "judgment", "execution", "evaluation"]
    assert r["verdict"] is not None


def test_failed_run_routes_to_diagnosis(monkeypatch):
    monkeypatch.setattr(pipeline, "execute",
                        lambda **kw: {"run_result": _run_result(ok=False), "out_dir": None})
    r = pipeline.run_pipeline(tool="fastqc", fastq=GOOD, question="qc these reads")
    assert r["route"]["action"] == "run"
    assert r["trace"] == ["onboarding", "judgment", "execution", "diagnosis"]
    assert r["verdict"]["status"] == "failure"


# --- full end-to-end (only if fastqc is installed) -----------------------------

@pytest.mark.skipif(shutil.which("fastqc") is None, reason="fastqc not installed")
def test_happy_end_to_end(tmp_path):
    r = pipeline.run_pipeline(tool="fastqc", fastq=GOOD, question="qc these reads",
                              out_dir=str(tmp_path))
    assert r["route"]["action"] == "run"
    assert r["run_result"]["ok"]
    assert r["trace"] == ["onboarding", "judgment", "execution", "evaluation"]
    assert r["verdict"]["status"] in ("ok", "anomaly")
