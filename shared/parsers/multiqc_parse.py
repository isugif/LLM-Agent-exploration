"""Parse a MultiQC output directory into a metric dict.

MultiQC writes `multiqc_data/multiqc_general_stats.txt`, a TSV with one row per sample and columns
named like `FastQC_mqc-generalstats-fastqc-percent_duplicates`. We take the trailing metric name of
each column, average it across samples, and rename to the friendly names the expectation table uses
(so the same assay expectation table can score across tools where metrics overlap).

Returned dict is flat metric_name -> value, plus `n_samples`. Metrics not present are simply absent
(the evaluation harness scores only the ones it finds).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# map MultiQC general-stats metric suffixes -> our expectation-table metric names
_RENAME = {
    "percent_duplicates": "percent_duplication",
    "percent_gc": "percent_gc",
    "avg_sequence_length": "avg_sequence_length",
    "total_sequences": "total_sequences",
    "percent_fails": "percent_fails",
    "median_sequence_length": "median_sequence_length",
}


def _num(s: str):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _find_general_stats(out_dir: str) -> Path | None:
    for cand in Path(out_dir).rglob("multiqc_general_stats.txt"):
        return cand
    return None


def parse_multiqc(out_dir: str) -> dict[str, Any]:
    path = _find_general_stats(out_dir)
    if path is None:
        return {"error": f"no multiqc_general_stats.txt found under {out_dir}"}

    lines = path.read_text().splitlines()
    if len(lines) < 2:
        return {"error": "multiqc_general_stats.txt has no data rows"}

    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:] if ln.strip()]

    # collect numeric values per column (skip the Sample column at index 0)
    sums: dict[str, list[float]] = {}
    for col_idx in range(1, len(header)):
        suffix = header[col_idx].split("-")[-1].strip()
        name = _RENAME.get(suffix)
        if name is None:
            continue
        vals = [v for v in (_num(r[col_idx]) for r in rows if col_idx < len(r)) if v is not None]
        if vals:
            sums.setdefault(name, []).extend(vals)

    metrics: dict[str, Any] = {"n_samples": len(rows)}
    for name, vals in sums.items():
        metrics[name] = round(sum(vals) / len(vals), 4)   # mean across samples
    return metrics
