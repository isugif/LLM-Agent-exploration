"""Parse a FastQC output directory into the metrics the expectation table scores.

FastQC writes one `<sample>_fastqc.zip` per input containing `fastqc_data.txt`, a plain-text
file of modules delimited by `>>Module name<TAB>status` ... `>>END_MODULE`. We extract only the
handful of numbers our expectation table (contracts/expectations/rnaseq_qc.yaml) references.

Returned dict keys line up with that table's metric names so the evaluation harness can score
them directly.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any


def _read_data_txt(out_dir: str) -> str | None:
    """Return the contents of fastqc_data.txt from the single zip in out_dir (or None)."""
    zips = sorted(Path(out_dir).glob("*_fastqc.zip"))
    if not zips:
        return None
    zpath = zips[0]
    with zipfile.ZipFile(zpath) as zf:
        inner = next((n for n in zf.namelist() if n.endswith("fastqc_data.txt")), None)
        if inner is None:
            return None
        return zf.read(inner).decode("utf-8", errors="replace")


def _split_modules(text: str) -> dict[str, tuple[str, list[str]]]:
    """Return {module_name: (status, [body lines])}."""
    modules: dict[str, tuple[str, list[str]]] = {}
    name = status = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith(">>END_MODULE"):
            if name is not None:
                modules[name] = (status, body)
            name = status = None
            body = []
        elif line.startswith(">>"):
            head = line[2:].split("\t")
            name = head[0].strip()
            status = head[1].strip() if len(head) > 1 else ""
            body = []
        elif name is not None:
            body.append(line)
    return modules


def parse_fastqc(out_dir: str) -> dict[str, Any]:
    """Extract scored metrics + per-module pass/warn/fail statuses from a FastQC run."""
    text = _read_data_txt(out_dir)
    if text is None:
        return {"error": f"no *_fastqc.zip with fastqc_data.txt found in {out_dir}"}

    modules = _split_modules(text)
    metrics: dict[str, Any] = {
        "module_status": {name: st for name, (st, _) in modules.items()},
    }

    # --- Basic Statistics: %GC, total sequences, encoding, sequence length ---
    for line in modules.get("Basic Statistics", ("", []))[1]:
        if line.startswith("#"):
            continue
        key, _, val = line.partition("\t")
        key = key.strip()
        if key == "%GC":
            metrics["percent_gc"] = _num(val)
        elif key == "Total Sequences":
            metrics["total_sequences"] = _num(val)
        elif key == "Sequence length":
            metrics["sequence_length"] = val.strip()
        elif key == "Encoding":
            metrics["encoding"] = val.strip()

    # --- Per base sequence quality: mean of the per-position Mean column ---
    means = []
    for line in modules.get("Per base sequence quality", ("", []))[1]:
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) >= 2:
            m = _num(cols[1])
            if m is not None:
                means.append(m)
    if means:
        metrics["per_base_mean_quality"] = round(sum(means) / len(means), 2)

    # --- Sequence Duplication Levels: 100 - Total Deduplicated Percentage ---
    for line in modules.get("Sequence Duplication Levels", ("", []))[1]:
        if line.startswith("#Total Deduplicated Percentage"):
            dedup = _num(line.split("\t")[-1])
            if dedup is not None:
                metrics["percent_duplication"] = round(100.0 - dedup, 2)

    # --- Overrepresented sequences: percentage of the top hit (0 if module empty) ---
    over_rows = [l for l in modules.get("Overrepresented sequences", ("", []))[1]
                 if l.strip() and not l.startswith("#")]
    top = 0.0
    for row in over_rows:
        cols = row.split("\t")
        if len(cols) >= 3:
            top = max(top, _num(cols[2]) or 0.0)
    metrics["overrepresented_percent"] = round(top, 4)

    # --- Adapter Content: max adapter percentage across all positions/adapters ---
    max_adapter = 0.0
    for line in modules.get("Adapter Content", ("", []))[1]:
        if line.startswith("#") or not line.strip():
            continue
        for cell in line.split("\t")[1:]:      # skip the position column
            v = _num(cell)
            if v is not None:
                max_adapter = max(max_adapter, v)
    metrics["adapter_content_max_percent"] = round(max_adapter, 4)

    return metrics


def _num(s: str) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None
