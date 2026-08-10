"""Tests for the alignment path: the reference-input plumbing, minimap2's SAM parser, the
reference-required refusal, and (if minimap2 is installed) a real end-to-end alignment.

Run: conda run -n nooa python -m pytest tests/test_align.py -q
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared import contracts_lib as cl                        # noqa: E402
from shared.execution.runner import run_tool                  # noqa: E402
from shared.parsers.minimap2_parse import parse_minimap2      # noqa: E402


# --- SAM parser (no minimap2 needed) -------------------------------------------

_SAM = """@HD\tVN:1.6
@SQ\tSN:ref\tLN:100
r1\t0\tref\t1\t60\t10M\t*\t0\t0\tACGTACGTAC\t*
r2\t0\tref\t5\t40\t10M\t*\t0\t0\tACGTACGTAC\t*
r3\t4\t*\t0\t0\t*\t*\t0\t0\tACGTACGTAC\t*
r2\t256\tref\t8\t0\t10M\t*\t0\t0\tACGTACGTAC\t*
r1\t2048\tref\t50\t60\t5M\t*\t0\t0\tACGTA\t*
"""


def test_parse_minimap2_counts_primary_only(tmp_path):
    (tmp_path / "aln.sam").write_text(_SAM)
    m = parse_minimap2(str(tmp_path))
    assert m["n_reads"] == 3                # r1, r2, r3 primary (secondary 256 / supplementary 2048 excluded)
    assert m["n_mapped"] == 2              # r1, r2 mapped; r3 unmapped (flag 4)
    assert m["percent_mapped"] == pytest.approx(66.67, abs=0.01)
    assert m["mean_mapq"] == pytest.approx(50.0)   # (60+40)/2


def test_parse_minimap2_no_sam(tmp_path):
    assert "error" in parse_minimap2(str(tmp_path))


# --- runner reference plumbing (uses `echo`, no minimap2 needed) ---------------

def test_runner_substitutes_reference():
    contract = {"id": "echotool", "execution": {"argv": ["echo", "ref={reference}", "in={input}"]}}
    r = run_tool(contract, "reads.fq", "/tmp", reference="genome.fa")
    assert r.ok and "ref=genome.fa" in r.stdout and "in=reads.fq" in r.stdout


def test_runner_errors_when_reference_missing():
    contract = {"id": "needsref", "execution": {"argv": ["echo", "{reference}"]}}
    r = run_tool(contract, "reads.fq", "/tmp", reference=None)   # argv needs {reference}, none given
    assert not r.ok and "requires a reference" in (r.error or "")


# --- harness gate: minimap2 refuses before compute without a reference ---------

def test_minimap2_refuses_without_reference():
    from langgraph_impl.graph import build_graph
    import os
    os.environ["OLLAMA_HOST"] = "http://localhost:1"           # force deterministic (NullProvider)
    final = build_graph().invoke({
        "tool": "minimap2", "fastq": str(REPO / "tests/inputs/good.fastq.gz"),
        "reference": None, "question": "align these reads", "deliverable": "align these reads",
        "out_dir": None,
    })
    assert final["route"]["action"] == "refuse"
    assert any("reference_provided" in f for f in final["route"]["precondition_failures"])


# --- end-to-end (only if minimap2 is installed) --------------------------------

@pytest.mark.skipif(shutil.which("minimap2") is None, reason="minimap2 not installed")
def test_minimap2_end_to_end(tmp_path):
    ref = tmp_path / "ref.fasta"
    ref.write_text(">ref\n" + "ACGTACGTACGTACGTACGTACGTACGTACGT" * 4 + "\n")
    reads = tmp_path / "reads.fastq"
    seq = "ACGTACGTACGTACGTACGTACGT"
    reads.write_text("".join(f"@r{i}\n{seq}\n+\n{'I'*len(seq)}\n" for i in range(20)))
    contract = cl.load_contract("minimap2")
    out = tmp_path / "out"
    r = run_tool(contract, str(reads), str(out), reference=str(ref))
    assert r.ok, r.error
    m = parse_minimap2(str(out))
    assert "percent_mapped" in m and m["n_reads"] == 20
