"""Probe an alignment file (BAM/SAM/CRAM) for MEASURED facts — the onboarding half for tools that
consume alignments (rustqc, samtools sort/markdup).

Uses `samtools` (a standard install) to read the header and sample records, so it works for binary
BAM/CRAM as well as text SAM. The facts mirror the names used in those tools' preconditions
(`format`, `sorted`, `dup_marked`, `n_records_sampled`, `mapped`) so contracts_lib.safe_eval can
assert against them — e.g. rustqc requires `measured.sorted == True and measured.dup_marked == True`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

_UNMAPPED = 0x4
_DUP = 0x400


def _fmt(path: str) -> str:
    ext = "".join(Path(path).suffixes[-1:]).lower()
    return {".bam": "bam", ".sam": "sam", ".cram": "cram"}.get(ext, "unknown")


def probe_alignment(path: str, sample_records: int = 5000) -> dict[str, Any]:
    """Return measured facts for a BAM/SAM/CRAM alignment."""
    if not os.path.exists(path):
        return {"format": "missing", "error": f"file not found: {path}"}
    fmt = _fmt(path)
    if fmt == "unknown":
        return {"format": "unknown", "error": "not a .bam/.sam/.cram file"}
    if shutil.which("samtools") is None:
        # can't read a binary alignment without samtools; report format only
        return {"format": fmt, "error": "samtools not on PATH — cannot inspect alignment",
                "sorted": False, "dup_marked": False, "n_records_sampled": 0, "mapped": 0}

    try:
        header = subprocess.run(["samtools", "view", "-H", path],
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"format": "unreadable", "error": str(exc)}
    if header.returncode != 0:
        return {"format": "unreadable", "error": (header.stderr or "").strip()[:200]}

    hdr = header.stdout
    sorted_by_coord = any(ln.startswith("@HD") and "SO:coordinate" in ln for ln in hdr.splitlines())
    # samtools markdup / Picard MarkDuplicates leave a @PG record — the reliable "was dup-marked" signal
    dup_marked = any(ln.startswith("@PG") and ("markdup" in ln.lower() or "markduplicates" in ln.lower())
                     for ln in hdr.splitlines())

    n = mapped = 0
    try:
        proc = subprocess.Popen(["samtools", "view", path], stdout=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            if n >= sample_records:
                break
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            try:
                flag = int(cols[1])
            except ValueError:
                continue
            n += 1
            if not (flag & _UNMAPPED):
                mapped += 1
            if not dup_marked and (flag & _DUP):     # a set dup flag also proves marking happened
                dup_marked = True
        proc.terminate()
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "format": fmt,
        "sorted": sorted_by_coord,
        "dup_marked": dup_marked,
        "n_records_sampled": n,
        "mapped": mapped,
    }
