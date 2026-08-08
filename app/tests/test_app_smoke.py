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


def test_intent_heuristic_offline():
    null = NullProvider()
    assert classify("tell me about reads.fastq.gz", null).intent == "describe_data"
    assert classify("hello there", null).intent == "other"


def test_intent_is_typed():
    assert Intent().intent == "other"


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
    r = client.post("/api/chat", json={"message": "add the tool star", "provider": "auto"})
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
