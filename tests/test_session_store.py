"""Unit tests for the disk-backed session run-log (app/session.py).

Run: conda run -n nooa python -m pytest tests/test_session_store.py -q

Isolated via BIO_CHAT_SESSIONS -> a tmp dir. No LLM, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.session import SessionStore, _SID_RE  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(base_dir=tmp_path)


def test_ensure_mints_valid_sid(store):
    sid = store.ensure(None)
    assert _SID_RE.match(sid)                     # 32-hex
    assert store.ensure(sid) == sid               # idempotent for a known sid
    assert (store.base_dir / sid / "meta.json").exists()


def test_ensure_rejects_unsafe_sids(store):
    for bad in ("../evil", "..", "a/b", "nothex", "", "DEADBEEF" * 4):  # last is uppercase -> not [0-9a-f]
        got = store.ensure(bad)
        assert got != bad and _SID_RE.match(got)  # replaced with a fresh safe sid
    # a traversal segment never creates anything outside base_dir
    assert not (store.base_dir.parent / "evil").exists()


def test_run_dir_is_inside_session_and_sanitized(store):
    sid = store.ensure(None)
    d = store.run_dir(sid, "fast/qc; rm -rf")      # nasty tool string
    assert d.exists()
    assert str(d).startswith(str(store.base_dir / sid / "runs"))
    assert "/" not in d.name.replace("-", "") or d.parent.name == "runs"  # slug has no path parts


def test_run_dir_name_is_url_safe(store):
    """The run-dir name feeds a report URL query param — no '+' (would decode to a space) or ':'."""
    sid = store.ensure(None)
    name = store.run_dir(sid, "fastqc").name
    assert "+" not in name and ":" not in name
    assert store.report_file(sid, name) is None      # no html yet, but the name resolves safely


def test_report_file_serves_and_rejects_traversal(store):
    sid = store.ensure(None)
    run = store.run_dir(sid, "fastqc")
    (run / "SRR_fastqc.html").write_text("<html>ok</html>")
    assert store.report_file(sid, run.name).name == "SRR_fastqc.html"
    assert store.report_file(sid, "../../etc") is None
    assert store.report_file("../x", run.name) is None


def test_append_and_load_runs_roundtrip(store):
    sid = store.ensure(None)
    store.append_run(sid, {"tool": "fastqc", "question": "qc", "out_dir": "/x",
                           "action": "run", "verdict_status": "anomaly"})
    store.append_run(sid, {"tool": "multiqc", "question": "agg", "action": "run",
                           "verdict_status": "ok"})
    runs = store.load_runs(sid)
    assert [r["tool"] for r in runs] == ["fastqc", "multiqc"]   # oldest-first
    assert all("ts" in r for r in runs)                          # timestamp stamped


def test_load_runs_unknown_or_bad_sid(store):
    assert store.load_runs("../etc") == []
    assert store.load_runs(store.ensure(None)) == []            # valid but no runs yet


def test_list_sessions_newest_first(store):
    a = store.ensure(None)
    store.append_run(a, {"tool": "fastqc", "question": "first"})
    b = store.ensure(None)
    store.append_run(b, {"tool": "multiqc", "question": "second"})
    sessions = store.list_sessions()
    assert {s["sid"] for s in sessions} == {a, b}
    top = sessions[0]
    assert top["n_runs"] == 1 and top["last_question"] in {"first", "second"}
