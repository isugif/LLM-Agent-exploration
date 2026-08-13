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


def test_run_tool_pattern_runs_matching_files_in_one_call(tmp_path, monkeypatch):
    """'run fastqc on the snf files' -> a single run_tool(pattern='snf') runs EVERY snf FASTQ and
    nothing else. Deterministic file selection; the model never enumerates."""
    import shutil, gzip
    if shutil.which("fastqc") is None:
        import pytest
        pytest.skip("fastqc not installed")
    from app import workdir
    for nm in ("snf2_1.fastq.gz", "snf2_2.fastq.gz", "wt_1.fastq.gz"):
        with gzip.open(tmp_path / nm, "wt") as fh:
            fh.write("@r\nACGTACGTAC\n+\nIIIIIIIIII\n")
    monkeypatch.setattr(workdir, "_workdir", tmp_path)
    events, sid = _drive([
        AgentAction(tool="run_tool", args={"tool": "fastqc", "pattern": "snf"}),
        AgentAction(answer="done"),
    ])
    files = sorted(Path(r["file"]).name for r in STORE.load_runs(sid))
    assert files == ["snf2_1.fastq.gz", "snf2_2.fastq.gz"]     # only snf, not wt — one call, two runs
    judged = [d for (n, d) in events if n == "stage" and d.get("stage") == "judgment"]
    assert len(judged) == 2


def test_batch_extracts_declared_facts_once(tmp_path, monkeypatch):
    """A multi-file batch does onboarding's LLM extraction ONCE (first file), reusing the declared
    facts for the rest — the fix for the big per-file delay."""
    import gzip
    from app import workdir
    import shared.harnesses.onboarding as ob
    calls = {"n": 0}

    class CountProvider:
        name = "count"
        def extract(self, schema, system, prompt):
            calls["n"] += 1
            return None                                   # -> declared stays {} (empty, but not None)
        def complete(self, system, prompt):
            return ""

    monkeypatch.setattr(ob, "get_provider", lambda name=None, model=None: CountProvider())
    for nm in ("snf2_1.fastq.gz", "snf2_2.fastq.gz"):
        with gzip.open(tmp_path / nm, "wt") as fh:
            fh.write("@r\nACGTACGTAC\n+\nIIIIIIIIII\n")
    monkeypatch.setattr(workdir, "_workdir", tmp_path)
    _drive([AgentAction(tool="run_tool", args={"tool": "fastqc", "pattern": "snf"}),
            AgentAction(answer="done")])
    assert calls["n"] == 1                                # one extraction for the whole 2-file batch


def test_run_tool_aggregator_defaults_to_runs_dir():
    """'run multiqc' with no path -> deterministically defaults to the session runs/ dir (not a guessed
    folder); the empty session then refuses on reports_present."""
    events, sid = _drive([
        AgentAction(tool="run_tool", args={"tool": "multiqc"}),
        AgentAction(answer="no reports yet"),
    ])
    logs = [d.get("text", "") for (n, d) in events if n == "log"]
    assert any("aggregating reports in" in t for t in logs)    # defaulted a dir, didn't ask for a file
    judged = [d for (n, d) in events if n == "stage" and d.get("stage") == "judgment"]
    assert judged and judged[0]["action"] == "refuse"
    assert any("reports_present" in f for f in judged[0].get("precondition_failures", []))


def test_build_args_from_flat_fields():
    """The model fills FLAT typed fields; the loop assembles the tool's arg dict deterministically."""
    from app.agent_loop import _build_args
    a = AgentAction(tool="run_tool", bio_tool="minimap2", pattern="snf", reference="ref.fasta")
    assert _build_args(a) == {"tool": "minimap2", "pattern": "snf", "reference": "ref.fasta"}
    assert _build_args(AgentAction(tool="explain_tool", bio_tool="fastqc")) == {"tool": "fastqc"}
    assert _build_args(AgentAction(tool="find_tool", query="alignment")) == {"query": "alignment"}
    assert _build_args(AgentAction(tool="probe_data", path="x.fastq.gz")) == {"path": "x.fastq.gz"}


def test_toolname_literal_matches_registry():
    """The `tool` Literal (what structured output constrains the model to) stays in sync with TOOLS."""
    import typing
    ann = AgentAction.model_fields["tool"].annotation          # Optional[Literal[...]]
    literal = next(a for a in typing.get_args(ann) if typing.get_origin(a) is typing.Literal)
    assert set(typing.get_args(literal)) == set(agent_loop.TOOLS)


def test_flat_run_tool_pattern_end_to_end(tmp_path, monkeypatch):
    """The flat-field action (bio_tool + pattern, no nested args) runs every matching file in one call."""
    import shutil, gzip
    if shutil.which("fastqc") is None:
        import pytest
        pytest.skip("fastqc not installed")
    from app import workdir
    for nm in ("snf2_1.fastq.gz", "snf2_2.fastq.gz", "wt_1.fastq.gz"):
        with gzip.open(tmp_path / nm, "wt") as fh:
            fh.write("@r\nACGTACGTAC\n+\nIIIIIIIIII\n")
    monkeypatch.setattr(workdir, "_workdir", tmp_path)
    events, sid = _drive([
        AgentAction(tool="run_tool", bio_tool="fastqc", pattern="snf"),   # FLAT fields, no args dict
        AgentAction(answer="done"),
    ])
    files = sorted(Path(r["file"]).name for r in STORE.load_runs(sid))
    assert files == ["snf2_1.fastq.gz", "snf2_2.fastq.gz"]


def test_extract_retry_recovers_from_a_null():
    """A flaky first extraction (None) is retried once; a valid action on the retry recovers the turn
    instead of giving up with 'I couldn't form a valid next step'."""
    events, _ = _drive([None, AgentAction(answer="recovered")])   # first extract None, retry succeeds
    proses = [d.get("text", "") for (n, d) in events if n == "prose"]
    assert proses and proses[-1] == "recovered"
    assert not any("couldn't form a valid next step" in t for t in proses)


def test_degrades_without_llm():
    from shared.llm.provider import NullProvider
    sid = STORE.ensure(None)
    events = list(run_agent("hello", [], NullProvider(), sid))
    assert any(n == "prose" for (n, _) in events)
    assert events[-1][0] == "done"
