"""Deterministic smoke tests for the chat app (no LLM required — uses NullProvider path).

Covers: the FASTQ profiler, the intent heuristic fallback, and the /api/chat describe_data flow
end to end via FastAPI's TestClient (SSE body parsed by hand).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.intent import classify, Intent
from shared.probes.fastq_probe import profile_fastq
from shared.llm.provider import NullProvider


@pytest.fixture()
def fastq(tmp_path: Path) -> str:
    """A tiny 3-read FASTQ (36 bp, phred33)."""
    p = tmp_path / "reads.fastq.gz"
    rec = "@r{i}\n" + "A" * 36 + "\n+\n" + "I" * 36 + "\n"
    with gzip.open(p, "wt") as fh:
        for i in range(3):
            fh.write(rec.format(i=i))
    return str(p)


def test_profile_fastq(fastq):
    prof = profile_fastq(fastq)
    assert prof["facts"]["format"] == "fastq"
    assert prof["facts"]["encoding_guess"] == "phred33"
    assert prof["length_hist"] == {36: 3}
    assert len(prof["qual_by_pos"]) == 36
    assert prof["qual_by_pos"][0] == pytest.approx(40.0)   # 'I' = 73 -> Q40


def ground(message, history=None):
    """classify (offline -> 'other') then apply the deterministic resolver, as the router does."""
    from app import resolve
    it = classify(message, NullProvider(), history=history)
    resolve.resolve(it, message, history)
    return it


def test_intent_is_typed():
    assert Intent().intent == "other"


def test_resolve_offline_routing():
    assert ground("tell me about reads.fastq.gz").intent == "describe_data"
    assert ground("hello there").intent == "other"
    it = ground("run fastqc on reads.fastq.gz")
    assert it.intent == "run_pipeline" and it.tool == "fastqc" and it.files == ["reads.fastq.gz"]
    assert ground("install seqkit").intent == "add_tool"
    assert ground("install seqkit").tool == "seqkit"
    assert ground("add the tool star").tool == "star"


def test_add_tool_event_mapping():
    from app.capabilities import add_tool as at
    ev = at.to_event("curate", {"section": "usage", "status": "valid", "fixes": 0, "items": 2})
    assert ev["stage"] == "curate" and ev["title"] == "Curate: usage"
    gate = at.to_event("hrr_gate", {"tool": "seqkit", "markers": 13, "reviewed": False})
    assert gate["title"] == "Human-review gate" and gate["markers"] == 13
    assert "not runnable" in at.summary_line("seqkit", True, "2.13.0", 13, ["usage", "options"], False)
    assert "couldn't install" in at.summary_line("nope", False, None, 0, [], False)


def test_resolve_explain_tool_offline():
    assert ground("tell me about fastqc").intent == "explain_tool"
    assert ground("tell me about fastqc").tool == "fastqc"
    assert ground("what parameters does fastqc have?").intent == "explain_tool"
    # an install request still wins over explain
    assert ground("install fastqc").intent == "add_tool"


def test_explain_tool_workbook_and_run():
    from app.capabilities import explain_tool as et
    assert "fastqc" in et.available_tools()
    wb = et.load_workbook("fastqc")
    assert wb and wb["sections"].get("meta")
    assert et.load_workbook("nope_xyz") is None
    out = et.run("what parameters does it have?", "fastqc", NullProvider(), history=[])
    assert out["panel"]["kind"] == "tool"
    assert len(out["panel"]["options"]) > 0            # parameters surfaced
    assert out["panel"]["boundaries"]                  # off-label boundaries present


def test_explain_tool_history_is_bounded():
    from app.capabilities import explain_tool as et
    huge = [{"role": "user", "content": "x" * 5000} for _ in range(20)]
    assert len(et._history_text(huge)) <= et.HIST_CAP   # sliding-window budget respected


def test_resolve_find_tool_offline():
    # tool-less discovery questions route to find_tool with no missing slot (they dispatch)
    for q in ("which tool is good for alignment?", "which tool takes fastq?",
              "recommend a tool for variant calling", "what tools do you have?"):
        it = ground(q)
        assert it.intent == "find_tool", q
    from app import resolve
    assert resolve.missing_slot(Intent(intent="find_tool")) is None
    # a NAMED-tool question is still explain_tool, not find_tool
    assert ground("tell me about fastqc").intent == "explain_tool"
    # a question with a FASTQ file is still describe_data, not find_tool
    assert ground("which tool should I run on reads.fastq.gz").intent != "find_tool"


def test_find_tool_capability_offline():
    from app.capabilities import find_tool as ft
    aln = ft.run("which tool is good for alignment?", NullProvider())
    assert aln["panel"]["kind"] == "catalog"
    tools = {t["tool"] for t in aln["panel"]["tools"]}
    assert {"hisat2", "star"} <= tools
    fq = ft.run("which tool takes fastq?", NullProvider())
    assert "fastqc" in {t["tool"] for t in fq["panel"]["tools"]}
    # honest empty answer for an undocumented category — never invents a tool
    none = ft.run("what tool for methylation?", NullProvider())
    assert none["panel"]["tools"] == []
    assert "don't have a documented tool" in none["prose"]


def test_chat_find_tool_sse(offline):
    client = TestClient(create_app())
    r = client.post("/api/chat", json={"message": "which tool takes fastq?", "provider": "auto"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert json.loads(events["meta"])["intent"] == "find_tool"
    panel = json.loads(events["panel"])
    assert panel["kind"] == "catalog"
    assert "fastqc" in {t["tool"] for t in panel["tools"]}


def test_resolve_named_tool_overrides_other():
    from app import resolve
    it = Intent(intent="other")
    resolve.resolve(it, "what does --export do? in multiqc", [])
    assert it.intent == "explain_tool" and it.tool == "multiqc"


def test_resolve_tool_from_history_and_missing_slot():
    from app import resolve
    hist = [{"role": "user", "content": "which parameter in multiqc outputs plots?"},
            {"role": "assistant", "content": "use --outdir"}]
    it = Intent(intent="other")
    resolve.resolve(it, "what does --export do?", hist)      # flag-style follow-up, tool from memory
    assert it.intent == "explain_tool" and it.tool == "multiqc"
    it2 = Intent(intent="explain_tool", tool="unknown")
    resolve.resolve(it2, "I meant the individual pngs", hist)
    assert it2.tool == "multiqc"
    # missing-slot check drives the uniform clarifying question
    assert resolve.missing_slot(Intent(intent="explain_tool", tool="unknown")) == "tool"
    assert resolve.missing_slot(Intent(intent="describe_data")) == "file"
    assert resolve.missing_slot(Intent(intent="explain_tool", tool="fastqc")) is None


def test_add_tool_docs_check_plan():
    from app.capabilities import add_tool as at
    # fastqc already documented -> no source/curate steps in the plan
    p = at.plan_for("fastqc")
    assert "source" not in p and not any(s.startswith("curate:") for s in p)
    assert at._missing("fastqc", ["usage", "options"]) == []
    # an undocumented tool -> every section missing
    assert at._missing("nope_xyz", ["usage", "options"]) == ["usage", "options"]
    assert "already installed and documented" in at.summary_line("fastqc", True, "0.12.1", 0, [], True)


def test_run_pipeline_event_mapping():
    from app.capabilities import run_pipeline as rp
    ev = rp.to_event("judgment", {"route": {"action": "refuse", "rationale": "nope",
                                            "precondition_failures": ["p1"], "boundary_hits": []}})
    assert ev["stage"] == "judgment" and ev["action"] == "refuse"
    ev2 = rp.to_event("evaluation", {"verdict": {"status": "anomaly", "findings": ["x"], "metrics": {}}})
    assert ev2["stage"] == "evaluation" and ev2["status"] == "anomaly"
    assert "refused" in rp.summary_line("refuse", None, "fastqc")


@pytest.fixture()
def offline(monkeypatch):
    """Force the deterministic NullProvider path so chat tests don't depend on a live LLM."""
    import app.api.routes_chat as rc
    monkeypatch.setattr(rc, "get_provider", lambda name=None: NullProvider())


def test_chat_describe_data_sse(fastq, offline):
    client = TestClient(create_app())
    r = client.post("/api/chat", json={"message": f"what can you tell me about {fastq}",
                                       "provider": "auto", "file": fastq})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert "panel" in events and "prose" in events
    panel = json.loads(events["panel"])
    labels = {row["label"] for row in panel["facts"]}
    assert "Quality encoding" in labels
    assert panel["length_hist"] == {"36": 3} or panel["length_hist"] == {36: 3}
    assert len(panel["qual_by_pos"]) == 36


def test_chat_stub_for_unwired_intent(offline):
    client = TestClient(create_app())
    # offline heuristic maps a non-file, non-install/run message to 'other' -> a stub
    r = client.post("/api/chat", json={"message": "help me plan my experiment", "provider": "auto"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert "panel" not in events                      # stub carries no data panel
    assert "isn't wired up yet" in json.loads(events["prose"])["text"]


def _parse_sse(text: str) -> dict:
    """Collapse an SSE body into {event_name: data_string} (last one wins)."""
    out = {}
    for block in text.split("\n\n"):
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            out[event] = data
    return out
