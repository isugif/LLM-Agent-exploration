"""Unit tests for the contract enforcement engine (shared/contracts_lib.py).

Run: conda run -n nooa python -m pytest tests/test_contracts_lib.py -q

Focus: the safe_eval semantics that judgment routing depends on —
  * a MISSING fact is uniformly "uncheckable" (warning), never a silent False (block);
  * and/or short-circuit so authors can guard comparisons behind existence checks;
  * only the whitelisted expression surface evaluates at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.contracts_lib import evaluate_preconditions, safe_eval, score_metric  # noqa: E402


NS = {"declared": {"assay": "rna-seq"}, "measured": {"format": "fastq", "n_reads": 10}}


# --- safe_eval: allowed surface ------------------------------------------------

def test_comparisons_and_boolops():
    assert safe_eval("measured.format == 'fastq'", NS)
    assert safe_eval("measured.n_reads > 0 and declared.assay == 'rna-seq'", NS)
    assert safe_eval("measured.format in ['fastq', 'fasta']", NS)
    assert safe_eval("not measured.n_reads > 100", NS)
    assert safe_eval("0 < measured.n_reads <= 10", NS)          # chained


def test_missing_fact_raises_not_false():
    """The regression this guards: `measured.layout == 'PE'` with layout absent must NOT
    quietly evaluate to False (which would BLOCK); it must raise so the precondition is
    treated as uncheckable (warning)."""
    with pytest.raises(KeyError):
        safe_eval("measured.layout == 'PE'", NS)
    with pytest.raises(KeyError):
        safe_eval("measured.read_count > 0", NS)


def test_short_circuit_guards_missing_facts():
    # first clause is False -> second clause (missing fact) must never evaluate
    assert safe_eval("measured.format == 'fasta' and measured.layout == 'PE'", NS) is False
    assert safe_eval("measured.format == 'fastq' or measured.layout == 'PE'", NS) is True


@pytest.mark.parametrize("expr", [
    "__import__('os').system('true')",     # call
    "measured.__class__",                  # attribute on non-namespace... still Attribute on Name
    "open('/etc/passwd')",                 # call + unknown name
    "[x for x in []]",                     # comprehension
    "measured.format is None",             # `is` comparator not whitelisted
])
def test_disallowed_expressions_raise(expr):
    with pytest.raises((ValueError, KeyError)):
        safe_eval(expr, NS)


# --- evaluate_preconditions: block vs warning routing ---------------------------

def _pc(assert_expr, severity="block"):
    return {"id": "t", "assert": assert_expr, "severity": severity, "message": "m"}


def test_failed_precondition_blocks():
    contract = {"preconditions": [_pc("measured.format == 'fasta'")]}
    blocking, warnings = evaluate_preconditions(contract, {}, NS["measured"])
    assert len(blocking) == 1 and not warnings


def test_missing_fact_is_warning_not_block():
    """Equality and ordering asserts over a missing fact must both land in warnings."""
    contract = {"preconditions": [_pc("measured.layout == 'PE'"),
                                  _pc("measured.read_count > 0")]}
    blocking, warnings = evaluate_preconditions(contract, {}, NS["measured"])
    assert not blocking
    assert len(warnings) == 2
    assert all("uncheckable" in w["message"] for w in warnings)


def test_guarded_expression_blocks_cleanly():
    """Short-circuit lets an author guard a comparison; the guard failing -> real block."""
    contract = {"preconditions": [_pc("measured.format == 'fasta' and measured.read_count > 0")]}
    blocking, warnings = evaluate_preconditions(contract, {}, NS["measured"])
    assert len(blocking) == 1 and not warnings


# --- score_metric: best-first tiering -------------------------------------------

EXPECT = {"metrics": {"percent_gc": {"ok": {"between": [35, 65]},
                                     "warn": {"between": [30, 70]},
                                     "fail": {"not_between": [30, 70]},
                                     "note": "n"}}}


def test_score_metric_best_first():
    assert score_metric(EXPECT, "percent_gc", 50)["tier"] == "ok"    # inside ok AND warn -> ok wins
    assert score_metric(EXPECT, "percent_gc", 32)["tier"] == "warn"
    assert score_metric(EXPECT, "percent_gc", 20)["tier"] == "fail"
    assert score_metric(EXPECT, "missing_metric", 1)["tier"] == "unknown"
