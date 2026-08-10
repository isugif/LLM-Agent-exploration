"""Unit tests for the tool catalog + category taxonomy (find_tool's retrieval substrate).

Run: conda run -n nooa python -m pytest tests/test_catalog.py -q

Deterministic — no LLM, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import catalog  # noqa: E402
from shared.knowledge import categories as cat  # noqa: E402


# --- taxonomy ------------------------------------------------------------------

def test_seed_categories_are_in_vocabulary():
    for tool, (category, _url) in cat._seed().items():
        assert category in cat.CATEGORIES, f"{tool} seeded with off-vocab category {category!r}"


def test_seed_lookup_and_repo():
    assert cat.seed_category("star") == "Read_Alignment_and_Mapping"
    assert cat.seed_category("STAR") == "Read_Alignment_and_Mapping"       # case-insensitive
    assert cat.seed_category("trimmomatic") == "Sequence_Data_Processing_and_Quality_Control"
    assert cat.seed_category("not_a_real_tool") is None
    assert cat.repo_for("star") and cat.repo_for("star").startswith("https://github.com/")


def test_category_from_text_synonyms():
    assert cat.category_from_text("which tool is good for alignment") == "Read_Alignment_and_Mapping"
    assert cat.category_from_text("an rna-seq expression tool") == "RNA_Analysis"
    assert cat.category_from_text("variant calling") == "Variant_Calling_and_Genotype_Analysis"
    assert cat.category_from_text("just say hello") is None


# --- catalog -------------------------------------------------------------------

def test_catalog_covers_documented_tools():
    catalog.invalidate()
    tools = {r["tool"] for r in catalog.catalog()}
    assert {"fastqc", "multiqc", "star", "hisat2", "seqkit"} <= tools


def test_record_shape_and_category_sources():
    catalog.invalidate()
    by = {r["tool"]: r for r in catalog.catalog()}
    for key in ("tool", "version", "summary", "category_tags", "input_formats",
                "output_formats", "runtimes", "reviewed"):
        assert key in by["fastqc"]
    # fastqc's category comes from its meta.category_tags; star's from the seed table
    assert "Sequence_Data_Processing_and_Quality_Control" in by["fastqc"]["category_tags"]
    assert by["star"]["category_tags"] == ["Read_Alignment_and_Mapping"]
    # an HRR placeholder summary is not surfaced as a real summary
    assert not by["star"]["summary"].startswith("HRR_")


def test_find_by_input_format():
    catalog.invalidate()
    hits = {r["tool"] for r in catalog.find(input_format="fastq")}
    assert "fastqc" in hits and "hisat2" in hits
    assert "multiqc" not in hits            # multiqc takes a report_dir, not fastq


def test_find_by_category():
    catalog.invalidate()
    aln = {r["tool"] for r in catalog.find(category="Read_Alignment_and_Mapping")}
    assert {"hisat2", "star", "minimap2"} <= aln       # documented aligners (minimap2 is runnable)
    assert catalog.find(category="Methylation") == []   # nothing documented there yet


def test_invalidate_rebuilds():
    catalog.invalidate()
    first = catalog.catalog()
    assert catalog.catalog() is first      # cached (same object)
    catalog.invalidate()
    assert catalog.catalog() is not first  # rebuilt after invalidate
