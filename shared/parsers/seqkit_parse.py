"""Parse `seqkit stats -a -T` output (a TSV) into the metrics the expectation table scores.

seqkit writes one header row + one row per input file. We read by COLUMN NAME (not position), so the
parser is robust to seqkit adding/reordering columns across versions. We surface the handful of
columns worth scoring/reporting; unknown columns are ignored.

Returned keys line up with shared/contracts/expectations/seqkit_stats.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# seqkit column name -> our metric name (values are read by header, tolerant to version drift)
_COLS = {
    "num_seqs": "num_seqs",
    "sum_len": "sum_len",
    "min_len": "min_len",
    "avg_len": "avg_len",
    "max_len": "max_len",
    "N50": "n50",
    "GC(%)": "percent_gc",
    "Q20(%)": "percent_q20",
    "Q30(%)": "percent_q30",
    "AvgQual": "avg_qual",
}


def _num(s: str):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_seqkit(out_dir: str) -> dict[str, Any]:
    tsvs = sorted(Path(out_dir).glob("*.tsv"))
    if not tsvs:
        return {"error": f"no seqkit stats .tsv found in {out_dir}"}
    lines = tsvs[0].read_text().splitlines()
    if len(lines) < 2:
        return {"error": "seqkit stats output has no data row"}

    header = lines[0].split("\t")
    row = lines[1].split("\t")                 # first input file's stats
    by_name = {h.strip(): (row[i] if i < len(row) else "") for i, h in enumerate(header)}

    metrics: dict[str, Any] = {}
    for col, key in _COLS.items():
        if col in by_name:
            v = _num(by_name[col])
            if v is not None:
                metrics[key] = round(v, 4)
    if not metrics:
        return {"error": "could not read any known columns from seqkit stats output"}
    return metrics
