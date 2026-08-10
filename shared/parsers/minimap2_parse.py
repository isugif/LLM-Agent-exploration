"""Parse a minimap2 alignment (SAM) into the metrics the expectation table scores.

minimap2 writes `<out_dir>/aln.sam` (per the tool's execution.argv). We read it with the standard
library only — no samtools/pysam — counting PRIMARY records (excluding secondary/supplementary) and
how many are mapped, to compute a mapping rate and mean MAPQ.

Returned keys line up with shared/contracts/expectations/alignment_qc.yaml so the evaluation harness
scores them directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# SAM FLAG bits
_UNMAPPED = 0x4
_SECONDARY = 0x100
_SUPPLEMENTARY = 0x800


def parse_minimap2(out_dir: str) -> dict[str, Any]:
    """Extract alignment metrics from the SAM in `out_dir`."""
    sams = sorted(Path(out_dir).glob("*.sam"))
    if not sams:
        return {"error": f"no .sam alignment found in {out_dir}"}

    n_primary = n_mapped = 0
    mapq_sum = 0
    try:
        with open(sams[0]) as fh:
            for line in fh:
                if line.startswith("@"):          # header
                    continue
                cols = line.split("\t")
                if len(cols) < 5:
                    continue
                flag = int(cols[1])
                if flag & (_SECONDARY | _SUPPLEMENTARY):   # count each read once (primary only)
                    continue
                n_primary += 1
                if not (flag & _UNMAPPED):
                    n_mapped += 1
                    mapq_sum += int(cols[4])
    except (OSError, ValueError) as exc:
        return {"error": f"could not parse SAM: {exc}"}

    if n_primary == 0:
        return {"error": "SAM contained no primary alignment records"}

    return {
        "n_reads": n_primary,
        "n_mapped": n_mapped,
        "percent_mapped": round(100.0 * n_mapped / n_primary, 2),
        "mean_mapq": round(mapq_sum / n_mapped, 2) if n_mapped else 0.0,
    }
