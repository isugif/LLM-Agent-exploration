"""Tests for the Phase B tool-use loop (app/agent_loop.py).

Uses a SCRIPTED provider (returns queued AgentActions) so the loop is deterministic without a live
model. Asserts the trust-boundary properties: the tool surface has no shell/exec, run_tool refuses
before compute, and read_file stays scoped to the working directory.

Run: conda run -n nooa python -m pytest tests/test_agent_loop.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["OLLAMA_HOST"] = "http://localhost:1"     # deterministic; the loop uses the fake provider

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app import agent_loop                             # noqa: E402
from app.agent_loop import AgentAction, run_agent      # noqa: E402
from app.session import STORE                          # noqa: E402

GOOD = str(REPO / "tests/inputs/good.fastq.gz")
BADQUAL = str(REPO / "tests/inputs/badqual.fastq.gz")


class ScriptedProvider:
    """A provider whose `extract` replays a queue of AgentActions (ignores prompt)."""
    name = "scripted"

    def __init__(self, actions):
        self._actions = list(actions)

    def extract(self, schema_model, system, prompt):
        return self._actions.pop(0) if self._actions else AgentAction(answer="done")

    def complete(self, system, prompt):
        return ""


def _drive(actions, message="go"):
    sid = STORE.ensure(None)
    return list(run_agent(message, [], ScriptedProvider(actions), sid)), sid


def test_tool_surface_has_no_raw_execution():
    assert "run_tool" in agent_loop.TOOLS
    for forbidden in ("shell", "bash", "exec", "system", "write_file"):
        assert forbidden not in agent_loop.TOOLS


def test_run_tool_refuses_before_compute():
    events, _ = _drive([
        AgentAction(tool="run_tool", args={"tool": "minimap2", "path": GOOD,
                                            "question": "align these reads"}),
        AgentAction(answer="It refused because there's no reference."),
    ])
    names = [n for (n, _) in events]
    # a judgment stage with action=refuse must appear, and no execution stage
    judged = [d for (n, d) in events if n == "stage" and d.get("stage") == "judgment"]
    assert judged and judged[0]["action"] == "refuse"
    assert not any(n == "stage" and d.get("stage") == "execution" for (n, d) in events)
    assert names[-2:] == ["prose", "done"]


def test_read_file_is_scoped_to_workdir():
    events, _ = _drive([
        AgentAction(tool="read_file", args={"path": "/etc/passwd"}),
        AgentAction(answer="blocked"),
    ])
    # the observation the loop fed back should be an out-of-scope error; nothing leaked to a panel
    logs = [d for (n, d) in events if n == "log"]
    assert any("read_file" in (d.get("text") or "") for d in logs)
    assert not any(n == "panel" for (n, _) in events)


def test_multi_file_run_each(monkeypatch):
    """The scenario the legacy brain couldn't do: inspect the folder, then run a tool on EACH of
    several files in one turn. Scripted here; a real model would pick the files from list_workdir."""
    import shutil
    if shutil.which("fastqc") is None:
        import pytest
        pytest.skip("fastqc not installed")
    events, sid = _drive([
        AgentAction(tool="list_workdir", args={}),
        AgentAction(tool="run_tool", args={"tool": "fastqc", "path": GOOD, "question": "qc"}),
        AgentAction(tool="run_tool", args={"tool": "fastqc", "path": BADQUAL, "question": "qc"}),
        AgentAction(answer="Ran fastqc on both files."),
    ])
    judged = [d for (n, d) in events if n == "stage" and d.get("stage") == "judgment"]
    assert len(judged) == 2 and all(j["action"] == "run" for j in judged)
    assert len(STORE.load_runs(sid)) == 2         # two runs recorded, one per DISTINCT file
    assert events[-2][0] == "prose" and events[-1][0] == "done"


def test_run_tool_is_idempotent_and_repeat_guard_stops(monkeypatch):
    """Regression for the observed runaway: repeating the SAME run_tool must execute once (no-op
    thereafter) and the loop must stop cleanly instead of looping forever."""
    import shutil
    if shutil.which("fastqc") is None:
        import pytest
        pytest.skip("fastqc not installed")
    same = AgentAction(tool="run_tool", args={"tool": "fastqc", "path": GOOD, "question": "qc"})
    # provider keeps proposing the identical action; the guard must break out
    events, sid = _drive([AgentAction(**same.model_dump()) for _ in range(6)])
    executions = [d for (n, d) in events if n == "stage" and d.get("stage") == "execution"]
    assert len(executions) == 1                   # executed once despite repeated proposals
    assert len(STORE.load_runs(sid)) == 1         # one run recorded, not six
    assert events[-1][0] == "done" and events[-2][0] == "prose"


def test_list_outputs_surfaces_run_output(monkeypatch):
    """The brain can see OUTPUT directories (not just inputs), enabling tool chaining."""
    import shutil
    if shutil.which("fastqc") is None:
        import pytest
        pytest.skip("fastqc not installed")
    events, sid = _drive([
        AgentAction(tool="run_tool", args={"tool": "fastqc", "path": GOOD, "question": "qc"}),
        AgentAction(tool="list_outputs", args={}),
        AgentAction(answer="done"),
    ])
    panels = [d for (n, d) in events if n == "panel" and d.get("kind") == "session"]
    assert panels and panels[-1]["runs"]
    run0 = panels[-1]["runs"][0]
    assert run0["tool"] == "fastqc" and run0["out_dir"]


def test_degrades_without_llm():
    from shared.llm.provider import NullProvider
    sid = STORE.ensure(None)
    events = list(run_agent("hello", [], NullProvider(), sid))
    assert any(n == "prose" for (n, _) in events)
    assert events[-1][0] == "done"
