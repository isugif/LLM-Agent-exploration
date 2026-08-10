"""Tests for the active working directory (app/workdir.py): set/validate, path resolution, and the
folder inspector.

Run: conda run -n nooa python -m pytest tests/test_workdir.py -q
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app import workdir                                       # noqa: E402


@pytest.fixture()
def wd(tmp_path, monkeypatch):
    """Point the process-global workdir at a tmp dir for the duration of a test."""
    monkeypatch.setattr(workdir, "_workdir", tmp_path)
    return tmp_path


def test_set_workdir_accepts_dir_rejects_file_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(workdir, "_workdir", workdir._workdir)   # snapshot -> auto-restore on teardown
    ok, msg = workdir.set_workdir(str(tmp_path))
    assert ok and str(tmp_path) in msg
    assert workdir.get_workdir() == tmp_path.resolve()
    f = tmp_path / "a.txt"; f.write_text("x")
    ok2, msg2 = workdir.set_workdir(str(f))
    assert not ok2 and "not a directory" in msg2
    ok3, _ = workdir.set_workdir(str(tmp_path / "nope"))
    assert not ok3


def test_resolve_path_workdir_then_fallback(wd):
    (wd / "reads.fastq.gz").write_text("x")
    assert workdir.resolve_path("reads.fastq.gz") == str(wd / "reads.fastq.gz")        # bare basename
    (wd / "sub").mkdir(); (wd / "sub" / "b.bam").write_text("x")
    assert workdir.resolve_path("sub/b.bam") == str(wd / "sub" / "b.bam")              # relative
    assert workdir.resolve_path("/does/not/exist.fastq") == "/does/not/exist.fastq"    # unchanged
    assert workdir.resolve_path(None) is None


def test_inspect_groups_by_type(wd):
    with gzip.open(wd / "r1.fastq.gz", "wt") as fh:
        fh.write("@r\nACGT\n+\nIIII\n")
    (wd / "aln.bam").write_text("x")
    (wd / "genome.fasta").write_text(">c\nACGT\n")
    (wd / "genes.gtf").write_text("x")
    (wd / "samples.csv").write_text("id,cond\n")
    (wd / "notes.md").write_text("x")                          # -> other
    (wd / ".hidden").write_text("x")                           # skipped
    info = workdir.inspect()
    assert info["workdir"] == str(wd)
    assert info["n_files"] == 6                                # hidden excluded
    kinds = {g["kind"]: g["count"] for g in info["groups"]}
    assert kinds["fastq"] == 1 and kinds["alignment"] == 1 and kinds["fasta"] == 1
    assert kinds["annotation"] == 1 and kinds["metadata"] == 1 and kinds["other"] == 1


def test_inspect_depth_limit(wd):
    (wd / "top.fastq").write_text("x")
    deep = wd / "a" / "b"; deep.mkdir(parents=True)
    (deep / "buried.fastq").write_text("x")                    # depth 2 -> excluded at default depth 1
    info = workdir.inspect(max_depth=1)
    files = [f for g in info["groups"] for f in g["files"]]
    assert "top.fastq" in files and not any("buried" in f for f in files)
