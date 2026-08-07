"""Probe a directory of tool reports for MEASURED facts (onboarding, aggregator tools).

Aggregators like MultiQC take a *directory* of other tools' outputs, not a FASTQ. This probe
measures what's actually in that directory so the aggregator's contract can assert against it
(e.g. "there is at least one recognized report to aggregate").

Returned facts mirror the names used in an aggregator contract's preconditions
(`format`, `n_reports`, `tools_detected`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# glob -> the tool that produced it (extend as more tools are added)
_REPORT_SIGNATURES = {
    "*_fastqc.zip": "fastqc",
    "*_fastqc.html": "fastqc",
    "*.flagstat": "samtools",
    "*Log.final.out": "star",
}


def probe_report_dir(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"format": "missing", "error": f"path not found: {path}"}
    if not os.path.isdir(path):
        return {"format": "not_a_dir", "error": f"expected a directory of reports, got a file: {path}"}

    root = Path(path)
    tools: dict[str, int] = {}
    total = 0
    for pattern, tool in _REPORT_SIGNATURES.items():
        n = len(list(root.rglob(pattern)))
        if n:
            tools[tool] = tools.get(tool, 0) + n
            total += n

    return {
        "format": "report_dir",
        "n_reports": total,
        "tools_detected": sorted(tools),
    }
