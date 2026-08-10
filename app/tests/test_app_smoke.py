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


def test_resolve_session_query_offline():
    for q in ("where did I write the fastqc output?", "what were the results of the summary again?",
              "what have I run so far?", "which tool did I run?"):
        assert ground(q).intent == "session_query", q
    # recall wins over discovery, but a plain discovery stays find_tool
    assert ground("which tool takes fastq?").intent == "find_tool"
    from app import resolve
    assert resolve.missing_slot(Intent(intent="session_query")) is None


@pytest.fixture()
def session_dir(tmp_path, monkeypatch):
    """Point the session store + dataset at tmp dirs so tests never touch ~/.bio_chat."""
    import importlib
    monkeypatch.setenv("BIO_CHAT_SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setenv("BIO_CHAT_DATASET", str(tmp_path / "dataset"))
    import app.session as s
    importlib.reload(s)                      # rebuild STORE against the tmp base_dir
    import app.capabilities.session_query as sq
    import app.api.routes_chat as rc
    importlib.reload(sq); importlib.reload(rc)
    return tmp_path


def test_chat_persists_transcript(session_dir, offline):
    client = TestClient(create_app())
    r = client.post("/api/chat", json={"message": "which tool takes fastq?", "provider": "auto"})
    sid = json.loads(_parse_sse(r.text)["meta"])["sid"]
    tr = client.get(f"/api/sessions/{sid}/transcript").json()["turns"]
    assert len(tr) == 1 and tr[0]["question"] == "which tool takes fastq?"
    kinds = {e["event"] for e in tr[0]["events"]}
    assert {"meta", "panel", "prose", "done"} <= kinds     # enough to repaint chat + tabs


def test_existing_path_resolves_from_workdir(tmp_path, monkeypatch):
    """A bare filename / wrong-dir slip resolves against the active workdir; unknown paths pass through."""
    import app.api.routes_chat as rc
    from app import workdir
    (tmp_path / "reads.fastq.gz").write_text("x")
    monkeypatch.setattr(workdir, "_workdir", tmp_path)
    assert rc._existing_path("reads.fastq.gz") == str(tmp_path / "reads.fastq.gz")        # bare name
    assert rc._existing_path("data/shared/reads.fastq.gz") == str(tmp_path / "reads.fastq.gz")  # by basename
    assert rc._existing_path("nope.fastq.gz") == "nope.fastq.gz"                          # unresolved unchanged


def test_resolve_workdir_offline():
    """'set my working directory / my data is in' -> set_workdir; 'what's in my folder' -> describe."""
    assert ground("set my working directory to /tmp/run1").intent == "set_workdir"
    assert ground("my data is in /data/yeast").intent == "set_workdir"
    assert ground("cd /tmp/x").intent == "set_workdir"
    assert ground("what's in my folder?").intent == "describe_workdir"
    assert ground("list my files").intent == "describe_workdir"
    assert ground("what's my working directory?").intent == "describe_workdir"
    # a run/describe request must NOT be hijacked by the workdir detectors
    assert ground("run fastqc on reads.fastq.gz").intent == "run_pipeline"
    assert ground("which tool takes fastq?").intent == "find_tool"


def test_workdir_path_extraction():
    from app import resolve
    assert resolve.workdir_path("set my working directory to /data/run1") == "/data/run1"
    assert resolve.workdir_path("my data is in ~/yeast/") == "~/yeast/"
    assert resolve.workdir_path("cd /tmp/x.") == "/tmp/x"        # trailing punctuation trimmed
    assert resolve.workdir_path("tell me about fastqc") is None


@pytest.fixture()
def reset_workdir():
    """Snapshot + restore the process-global workdir so a mutating test doesn't leak."""
    from app import workdir
    orig = workdir._workdir
    yield
    workdir._workdir = orig


def test_chat_workdir_api_and_dispatch(session_dir, offline, tmp_path, reset_workdir):
    import gzip
    from app import workdir
    data = tmp_path / "run1"; data.mkdir()
    with gzip.open(data / "a.fastq.gz", "wt") as fh:
        fh.write("@r\nACGT\n+\nIIII\n")
    (data / "samples.csv").write_text("id,cond\n")
    client = TestClient(create_app())
    # POST /api/workdir sets it; GET reads it back
    assert client.post("/api/workdir", json={"workdir": str(data)}).json()["workdir"] == str(data)
    assert client.get("/api/workdir").json()["workdir"] == str(data)
    client.post("/api/workdir", json={"workdir": str(tmp_path / "nope")}).status_code == 400
    # chat: "what's in my folder" -> a folder panel grouping the two files
    ev = _parse_sse(client.post("/api/chat", json={"message": "what's in my folder?"}).text)
    assert json.loads(ev["meta"])["intent"] == "describe_workdir"
    panel = json.loads(ev["panel"])
    assert panel["kind"] == "folder"
    kinds = {g["kind"] for g in panel["groups"]}
    assert {"fastq", "metadata"} <= kinds
    # chat: "my data is in <dir>" -> set_workdir, confirmed
    ev2 = _parse_sse(client.post("/api/chat", json={"message": f"my data is in {data}"}).text)
    assert json.loads(ev2["meta"])["intent"] == "set_workdir"
    assert workdir.get_workdir() == data


def test_run_pipeline_tool_name_resolution(session_dir, offline, monkeypatch, fastq):
    """A user-typed tool name is resolved (minimap->minimap2) or handled gracefully (bwa),
    never crashing on a missing manifest — the bug from the 'using minimap' session."""
    import app.api.routes_chat as rc
    from app.intent import Intent

    def fake_classify(tool):
        def _c(message, provider, history=None):
            return Intent(intent="run_pipeline", tool=tool, files=[fastq])   # a real file (exists)
        return _c

    client = TestClient(create_app())
    # 'minimap' -> documented aligner minimap2 -> reaches the reference-ask (proves resolution)
    monkeypatch.setattr(rc, "classify", fake_classify("minimap"))
    prose = json.loads(_parse_sse(client.post("/api/chat", json={"message": "run minimap on the reads"}).text)["prose"])["text"]
    assert "reference" in prose.lower()
    # 'bwa' is undocumented -> a clear message, not a FileNotFoundError
    monkeypatch.setattr(rc, "classify", fake_classify("bwa"))
    prose2 = json.loads(_parse_sse(client.post("/api/chat", json={"message": "run bwa on the reads"}).text)["prose"])["text"]
    assert "don't have a documented tool" in prose2 and "bwa" in prose2


def test_interrupted_turn_still_persists(session_dir, offline):
    """Closing the stream early (client abort) still flushes the turn via the generator's finally."""
    client = TestClient(create_app())
    sid = None
    with client.stream("POST", "/api/chat",
                       json={"message": "which tool takes fastq?", "provider": "auto"}) as r:
        for line in r.iter_lines():          # read one meta line to learn the sid, then bail
            if line.startswith("data:") and '"sid"' in line:
                sid = json.loads(line[5:].strip())["sid"]
                break                        # <- abort mid-stream
    assert sid
    turns = client.get(f"/api/sessions/{sid}/transcript").json()["turns"]
    assert len(turns) == 1                   # the partial turn was saved, not lost
    assert turns[0]["question"] == "which tool takes fastq?"


def test_settings_and_dataset_api(session_dir, offline):
    client = TestClient(create_app())
    assert client.get("/api/settings").json()["contribute_data"] is False
    assert client.post("/api/settings", json={"contribute_data": True}).json()["contribute_data"] is True
    assert client.get("/api/settings").json()["contribute_data"] is True
    # a chat turn logs at least the (question -> intent) row to the local dataset
    client.post("/api/chat", json={"message": "which tool takes fastq?", "provider": "auto"})
    assert client.get("/api/dataset/stats").json()["rows"] >= 1
    exp = client.get("/api/dataset/export")
    assert exp.status_code == 200 and '"kind": "intent"' in exp.text


def test_session_query_run_then_recall(session_dir):
    from app.session import STORE
    from app.capabilities import session_query as sq
    sid = STORE.ensure(None)
    STORE.append_run(sid, {"tool": "fastqc", "question": "qc these", "out_dir": "/out/fastqc-1",
                           "action": "run", "verdict_status": "anomaly",
                           "metrics": {"per_base_mean_quality": {"value": 38.5, "tier": "ok"}},
                           "findings": ["percent_gc=52 -> WARN"]})
    where = sq.run("where did I write the fastqc output?", sid, NullProvider())
    assert "/out/fastqc-1" in where["prose"]
    assert where["panel"]["kind"] == "session" and where["panel"]["count"] == 1
    result = sq.run("what were the results?", sid, NullProvider())
    assert "anomaly" in result["prose"]
    # empty session is honest, not invented
    empty = sq.run("what did I run?", STORE.ensure(None), NullProvider())
    assert "haven't run anything" in empty["prose"]


def test_session_aware_output_routing():
    """A question about a run's OUTPUT resolves to recall when the session has runs — the
    'what can you tell me about the fastqc output?' -> 'which file?' bug."""
    from app.intent import classify
    from app import resolve
    def route(msg, session=None):
        it = classify(msg, NullProvider()); resolve.resolve(it, msg, [], session); return it.intent
    has = {"has_runs": True, "tools": ["fastqc"]}
    none = {"has_runs": False, "tools": []}
    assert route("what can you tell me about the fastqc output?", has) == "session_query"
    assert route("show me the results", has) == "session_query"
    # without runs it must NOT hijack, and a named tool still explains
    assert route("what can you tell me about the fastqc output?", none) != "session_query"
    # a real file question is still describe_data even with runs present
    assert route("what can you tell me about reads.fastq.gz", has) == "describe_data"


def test_session_meta_facet_generalizes(session_dir):
    """'about this session' questions (id/size/tools) answer even on an empty session, and route."""
    from app.session import STORE
    from app.capabilities import session_query as sq
    from app.intent import classify
    from app import resolve
    def route(msg, session=None):
        it = classify(msg, NullProvider()); resolve.resolve(it, msg, [], session); return it.intent
    for q in ("what session is this?", "what's my session id?", "how many runs have I done?",
              "what tools have I used?"):
        assert route(q, {"has_runs": False, "tools": []}) == "session_query", q
    sid = STORE.ensure(None)
    empty = sq.run("what session is this?", sid, NullProvider())
    assert sid in empty["prose"] and empty["panel"]["kind"] == "session"
    assert empty["panel"]["sid"] == sid                     # id surfaced in the panel too
    STORE.append_run(sid, {"tool": "fastqc", "question": "qc", "out_dir": "/x", "action": "run"})
    full = sq.run("how many runs have I done?", sid, NullProvider())
    assert "1 run" in full["prose"] and "fastqc" in full["prose"]


def test_report_route_serves_and_rejects(session_dir):
    from app.session import STORE
    sid = STORE.ensure(None)
    run = STORE.run_dir(sid, "fastqc")
    (run / "SRR_fastqc.html").write_text("<html><body>FASTQC REPORT</body></html>")
    client = TestClient(create_app())
    ok = client.get(f"/api/sessions/{sid}/report", params={"run": run.name})
    assert ok.status_code == 200 and "FASTQC REPORT" in ok.text
    assert client.get(f"/api/sessions/{sid}/report", params={"run": "../../etc/passwd"}).status_code == 404
    assert client.get("/api/sessions/nothex/report", params={"run": run.name}).status_code == 404
    assert STORE.report_file(sid, "no_such_run") is None


def test_chat_echoes_sid_and_lists_sessions(session_dir, offline):
    client = TestClient(create_app())
    r = client.post("/api/chat", json={"message": "which tool takes fastq?", "provider": "auto"})
    assert r.status_code == 200
    meta = json.loads(_parse_sse(r.text)["meta"])
    sid = meta["sid"]
    assert len(sid) == 32                     # server minted + echoed a session id
    # a second call reusing the sid, then it should appear in the sessions list
    client.post("/api/chat", json={"message": "hello", "provider": "auto", "session_id": sid})
    listed = client.get("/api/sessions").json()["sessions"]
    assert sid in {s["sid"] for s in listed}
    assert client.get(f"/api/sessions/{sid}/runs").json()["sid"] == sid


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


def test_static_assets_are_no_cache():
    """UI assets carry Cache-Control: no-cache so an open tab never shows a stale app.js."""
    client = TestClient(create_app())
    r = client.get("/app.js")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")


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
