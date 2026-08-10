"""Confirm a BAM-producing transform (samtools sort / markdup) by re-probing its output BAM.

These tools don't emit QC numbers — their "result" is a transformed BAM for the next step. So the
parser re-runs the alignment probe on the produced BAM and reports what changed (sorted, dup_marked,
record count). With no expectation table, the evaluation harness reports these as an OK transform
rather than scoring biology.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.probes.aln_probe import probe_alignment


def parse_bam_transform(out_dir: str) -> dict[str, Any]:
    bams = sorted(Path(out_dir).glob("*.bam"))
    if not bams:
        return {"error": f"no output .bam produced in {out_dir}"}
    facts = probe_alignment(str(bams[0]))
    if facts.get("format") not in ("bam", "sam", "cram"):
        return {"error": f"output is not a readable alignment: {facts.get('error', facts.get('format'))}"}
    return {
        "output_sorted": facts.get("sorted"),
        "output_dup_marked": facts.get("dup_marked"),
        "n_records_sampled": facts.get("n_records_sampled"),
        "mapped": facts.get("mapped"),
    }
