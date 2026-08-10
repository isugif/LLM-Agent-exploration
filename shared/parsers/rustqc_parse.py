"""Parse rustqc's `--json-summary` output into the metrics the expectation table scores.

rustqc writes a JSON summary (per the contract's `-j {out_dir}/summary.json`). The scoreable RNA-seq
QC numbers live under `inputs[0].counting` (featureCounts assignment) and `inputs[0].dupradar`. We
surface a handful and rename to the expectation-table names; missing fields are simply absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_rustqc(out_dir: str) -> dict[str, Any]:
    jsons = sorted(Path(out_dir).rglob("summary.json")) or sorted(Path(out_dir).rglob("*.json"))
    if not jsons:
        return {"error": f"no rustqc summary.json found under {out_dir}"}
    try:
        data = json.loads(jsons[0].read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"could not read rustqc summary: {exc}"}

    inputs = data.get("inputs") or []
    if not inputs:
        return {"error": "rustqc summary has no input results"}
    rec = inputs[0]
    if rec.get("status") and rec["status"] != "success":
        return {"error": f"rustqc reported status={rec['status']} for the input"}

    counting = rec.get("counting", {}) or {}
    dupradar = rec.get("dupradar", {}) or {}
    metrics: dict[str, Any] = {}

    total = counting.get("total_reads")
    mapped = counting.get("mapped_reads")
    if total:
        metrics["total_reads"] = total
        if mapped is not None:
            metrics["percent_mapped"] = round(100.0 * mapped / total, 2)
    if counting.get("assigned_pct") is not None:
        metrics["percent_assigned"] = round(float(counting["assigned_pct"]), 2)
    if counting.get("duplicate_pct") is not None:
        metrics["percent_duplicate"] = round(float(counting["duplicate_pct"]), 2)
    if dupradar.get("slope") is not None:
        metrics["dupradar_slope"] = round(float(dupradar["slope"]), 3)

    if not metrics:
        return {"error": "rustqc summary had no recognizable QC metrics"}
    return metrics
