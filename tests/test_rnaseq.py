"""Tests for the RNA-seq QC path: the alignment probe, the runner's {annotation} second-input,
rustqc's prerequisite-catching preconditions, and the samtools transform tools.

Run: conda run -n nooa python -m pytest tests/test_rnaseq.py -q
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared import contracts_lib as cl                       # noqa: E402
from shared.execution.runner import run_tool                 # noqa: E402
from shared.parsers.rustqc_parse import parse_rustqc         # noqa: E402

_SORTED_MARKED = ("@HD\tVN:1.6\tSO:coordinate\n"
                  "@SQ\tSN:ref\tLN:100\n"
                  "@PG\tID:samtools.markdup\tPN:samtools\tCL:samtools markdup\n"
                  "r1\t0\tref\t1\t60\t5M\t*\t0\t0\tACGTA\tIIIII\n")
_RAW = ("@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:ref\tLN:100\n"
        "r1\t0\tref\t1\t60\t5M\t*\t0\t0\tACGTA\tIIIII\n")


# --- the contracts are human-reviewed (routable) -------------------------------

@pytest.mark.parametrize("tool", ["rustqc", "samtools_sort", "samtools_markdup"])
def test_contracts_reviewed(tool):
    c = cl.load_contract(tool)
    cl.validate_contract(c)
    assert cl.is_reviewed(c)                         # HRR markers gone


# --- alignment probe ----------------------------------------------------------

@pytest.mark.skipif(shutil.which("samtools") is None, reason="samtools not installed")
def test_aln_probe_detects_sorted_and_marked(tmp_path):
    from shared.probes.aln_probe import probe_alignment
    good = tmp_path / "sorted_marked.sam"; good.write_text(_SORTED_MARKED)
    raw = tmp_path / "raw.sam"; raw.write_text(_RAW)
    g = probe_alignment(str(good))
    assert g["format"] == "sam" and g["sorted"] is True and g["dup_marked"] is True
    r = probe_alignment(str(raw))
    assert r["format"] == "sam" and r["sorted"] is False and r["dup_marked"] is False
    assert probe_alignment(str(tmp_path / "nope.bam"))["format"] == "missing"


# --- runner: the {annotation} second input -------------------------------------

def test_runner_substitutes_annotation():
    contract = {"id": "t", "execution": {"argv": ["echo", "ann={annotation}", "in={input}"]}}
    r = run_tool(contract, "aln.bam", "/tmp", inputs={"annotation": "genes.gtf"})
    assert r.ok and "ann=genes.gtf" in r.stdout


def test_runner_errors_on_missing_annotation():
    contract = {"id": "rustqc", "execution": {"argv": ["echo", "{annotation}"]}}
    r = run_tool(contract, "aln.bam", "/tmp", inputs=None)
    assert not r.ok and "GTF annotation" in (r.error or "")


# --- rustqc catches its prerequisites (refuse before compute) ------------------

def _route(tool, fastq, annotation=None):
    import os
    os.environ["OLLAMA_HOST"] = "http://localhost:1"          # deterministic
    from langgraph_impl.graph import build_graph
    return build_graph().invoke({"tool": tool, "fastq": fastq, "annotation": annotation,
                                 "question": "qc", "deliverable": "qc", "out_dir": None})["route"]


def test_rustqc_refuses_non_alignment_input():
    route = _route("rustqc", str(REPO / "tests/inputs/good.fastq.gz"), annotation="x.gtf")
    assert route["action"] == "refuse"
    assert any("input_is_alignment" in f for f in route["precondition_failures"])


@pytest.mark.skipif(shutil.which("samtools") is None, reason="samtools not installed")
def test_rustqc_refuses_unsorted_and_unmarked(tmp_path):
    raw = tmp_path / "raw.sam"; raw.write_text(_RAW)
    route = _route("rustqc", str(raw), annotation="x.gtf")
    assert route["action"] == "refuse"
    fails = " ".join(route["precondition_failures"])
    assert "coordinate_sorted" in fails and "duplicate_marked" in fails
    assert "samtools sort" in fails and "samtools markdup" in fails    # the exact fix


# --- path/tool resolution ------------------------------------------------------

def test_resolvers_no_false_matches():
    from app import resolve
    assert resolve.aln_in("run rustqc on out.bam") == "out.bam"
    assert resolve.gtf_in("with genes.gtf here") == "genes.gtf"
    assert resolve.aln_in("reads.fastq.gz") is None          # not an alignment
    assert resolve.gtf_in("genome.fasta") is None


def test_tool_name_normalizes_spaces():
    from app.api.routes_chat import _resolve_tool_name
    assert _resolve_tool_name("samtools sort") == "samtools_sort"
    assert _resolve_tool_name("minimap") == "minimap2"
    assert _resolve_tool_name("bwa") is None
