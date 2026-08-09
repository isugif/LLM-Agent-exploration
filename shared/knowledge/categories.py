"""Tool-purpose taxonomy — the controlled vocabulary + seed tool→category mapping.

`category_tags` on a tool's meta section (schemas.py:MetaSection) is the authoritative purpose
label. This module supplies (a) the closed vocabulary those tags must come from, (b) a SEED
fallback for tools that haven't been tagged yet — derived from the user's curated
`tool_categories.tsv` (a `<github_url> <category>` table, also the source of GitHub URLs for a
future repo-based install path), and (c) a synonym map turning a user's words ("alignment") into a
category, for the deterministic side of the find_tool retriever.

Everything here is data + pure functions; no LLM, no network.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional

_TSV = Path(__file__).parent / "tool_categories.tsv"

# The closed vocabulary. `category_tags` values and seed categories must be one of these.
CATEGORIES: tuple[str, ...] = (
    "Sequence_Data_Processing_and_Quality_Control",
    "Read_Alignment_and_Mapping",
    "RNA_Analysis",
    "Variant_Calling_and_Genotype_Analysis",
    "Methylation",
    "Genome_Assembly_and_Annotation",
    "Functional_Prediction",
    "Protein_Sequence_Analysis",
    "Phylogenetic_and_Population_Genetics",
    "Metagenomics",
    "Visualization",
    "Workflow_Managers_and_Pipelines",
    "Miscellaneous_and_Utilities",
)

# user-facing keyword (substring, lowercased) -> category. Ordered longest/most-specific first so a
# more specific hit wins (checked in insertion order). Used by find_tool's structured filter.
SYNONYMS: dict[str, str] = {
    "quality control": "Sequence_Data_Processing_and_Quality_Control",
    "quality-control": "Sequence_Data_Processing_and_Quality_Control",
    "adapter": "Sequence_Data_Processing_and_Quality_Control",
    "trim": "Sequence_Data_Processing_and_Quality_Control",
    "filter reads": "Sequence_Data_Processing_and_Quality_Control",
    " qc": "Sequence_Data_Processing_and_Quality_Control",
    "quality": "Sequence_Data_Processing_and_Quality_Control",
    "align": "Read_Alignment_and_Mapping",
    "mapping": "Read_Alignment_and_Mapping",
    "mapper": "Read_Alignment_and_Mapping",
    "rna-seq": "RNA_Analysis",
    "rnaseq": "RNA_Analysis",
    "expression": "RNA_Analysis",
    "differential": "RNA_Analysis",
    "transcript": "RNA_Analysis",
    "quantif": "RNA_Analysis",
    "counts": "RNA_Analysis",
    "variant": "Variant_Calling_and_Genotype_Analysis",
    "snp": "Variant_Calling_and_Genotype_Analysis",
    "genotype": "Variant_Calling_and_Genotype_Analysis",
    "methylat": "Methylation",
    "bisulfite": "Methylation",
    "assembl": "Genome_Assembly_and_Annotation",
    "annotat": "Genome_Assembly_and_Annotation",
    "gene predict": "Functional_Prediction",
    "functional": "Functional_Prediction",
    "orf": "Functional_Prediction",
    "protein": "Protein_Sequence_Analysis",
    "phylogen": "Phylogenetic_and_Population_Genetics",
    "population genetic": "Phylogenetic_and_Population_Genetics",
    "metagenom": "Metagenomics",
    "visuali": "Visualization",
    "plot": "Visualization",
    "browser": "Visualization",
    "workflow": "Workflow_Managers_and_Pipelines",
    "pipeline manager": "Workflow_Managers_and_Pipelines",
    "nextflow": "Workflow_Managers_and_Pipelines",
    "snakemake": "Workflow_Managers_and_Pipelines",
}


def _tool_from_url(url: str) -> str:
    """Repo basename, lowercased: 'https://github.com/alexdobin/STAR' -> 'star'."""
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git").lower()


@functools.lru_cache(maxsize=1)
def _seed() -> dict[str, tuple[str, str]]:
    """tool_name -> (category, github_url), parsed from tool_categories.tsv (tab or space separated)."""
    table: dict[str, tuple[str, str]] = {}
    if not _TSV.exists():
        return table
    for line in _TSV.read_text().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        url, category = parts[0], parts[-1]
        if category in CATEGORIES:
            table[_tool_from_url(url)] = (category, url)
    return table


def seed_category(tool: str) -> Optional[str]:
    """Category for `tool` from the seed table, or None if it isn't listed."""
    hit = _seed().get((tool or "").lower())
    return hit[0] if hit else None


def repo_for(tool: str) -> Optional[str]:
    """The tool's GitHub URL from the seed table (for a future repo-based install path), or None."""
    hit = _seed().get((tool or "").lower())
    return hit[1] if hit else None


def category_from_text(text: str) -> Optional[str]:
    """First category whose synonym appears in `text` (lowercased), honoring SYNONYMS order."""
    low = f" {(text or '').lower()} "
    for keyword, category in SYNONYMS.items():
        if keyword in low:
            return category
    return None
