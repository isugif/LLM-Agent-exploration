"""Smoke tests for the stdio MCP server (mcp_server/server.py).

Asserts two things that matter for the trust boundary:
  1. The exposed tool surface is EXACTLY the harness tools — no shell/exec/write escape hatch.
  2. `run_tool` is self-guarding: it refuses (no compute) when judgment refuses, and otherwise runs
     the full onboarding->judgment->execute->evaluate trace.

Deterministic (Ollama forced unreachable). Run: conda run -n nooa python -m pytest tests/test_mcp_server.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys
import shutil
from pathlib import Path

import pytest

os.environ["OLLAMA_HOST"] = "http://localhost:1"     # force deterministic (NullProvider)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp_server import server as S                     # noqa: E402

GOOD = str(REPO / "tests/inputs/good.fastq.gz")

EXPECTED_TOOLS = {
    "probe_data", "list_catalog", "explain_tool", "find_tool",
    "onboard_experiment", "judge", "run_tool", "evaluate_output", "diagnose_failure",
}


def test_tool_surface_is_exactly_the_harness():
    # Exact-set equality IS the boundary check: no raw shell/exec/write tool can be present.
    names = {t.name for t in asyncio.run(S.server.list_tools())}
    assert names == EXPECTED_TOOLS


def test_probe_data_returns_measured_facts():
    facts = S.probe_data(GOOD)["facts"]
    assert facts.get("format") == "fastq"


def test_run_tool_refuses_before_compute():
    r = S.run_tool(tool="minimap2", path=GOOD, question="align these reads")
    assert r["route"]["action"] == "refuse"
    assert r["run_result"] is None and r["verdict"] is None
    assert r["trace"] == ["onboarding", "judgment", "refused"]


def test_onboard_experiment_builds_spec():
    spec = S.onboard_experiment(tool="fastqc", path=GOOD, question="qc these reads")["spec"]
    assert spec["measured"].get("format") == "fastq"


def test_diagnose_failure_returns_failure_verdict():
    v = S.diagnose_failure(tool="fastqc", stderr="boom", error="crashed", exit_code=1)["verdict"]
    assert v["status"] == "failure"


@pytest.mark.skipif(shutil.which("fastqc") is None, reason="fastqc not installed")
def test_run_tool_full_trace_when_allowed(tmp_path):
    r = S.run_tool(tool="fastqc", path=GOOD, question="qc these reads", out_dir=str(tmp_path))
    assert r["route"]["action"] == "run"
    assert r["run_result"]["ok"]
    assert r["trace"] == ["onboarding", "judgment", "execution", "evaluation"]
    assert r["verdict"]["status"] in ("ok", "anomaly")
