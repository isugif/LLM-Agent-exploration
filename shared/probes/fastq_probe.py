"""Probe a FASTQ file for MEASURED facts — the ground truth half of onboarding.

Pure standard library (gzip only). We sample the first N reads rather than reading the whole
file, which is enough to measure layout, read length, and quality encoding cheaply.

Returned facts intentionally mirror the names used in the FastQC contract's preconditions
(`format`, `n_reads_sampled`, `encoding_guess`, ...), so contracts_lib.safe_eval can assert
directly against them.
"""

from __future__ import annotations

import gzip
import os
from collections import Counter
from pathlib import Path
from typing import Any


def _open(path: str):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def _guess_encoding(min_q: int, max_q: int) -> str:
    """Guess the Phred offset from the observed ASCII range of quality chars.

    Modern Illumina is Phred+33 (Sanger). Old Illumina 1.3-1.7 used Phred+64.
    """
    if min_q < 33 or max_q > 126:
        return "unknown"
    if min_q < 59:
        return "phred33"            # '!' (33) .. only Sanger/Illumina1.8+ reaches this low
    if max_q > 74:
        return "phred64"            # chars above 'J' with a high floor suggest +64
    return "phred33"                # default for anything modern/ambiguous-but-plausible


def probe(path: str, sample_reads: int = 10000) -> dict[str, Any]:
    """Return measured facts for a single FASTQ (.fastq or .fastq.gz)."""
    if not os.path.exists(path):
        return {"format": "missing", "error": f"file not found: {path}"}

    lengths: list[int] = []
    min_q, max_q = 255, 0
    n = 0
    looks_fastq = False

    try:
        with _open(path) as fh:
            while n < sample_reads:
                header = fh.readline()
                if not header:
                    break
                seq = fh.readline()
                plus = fh.readline()
                qual = fh.readline()
                if not qual:
                    break
                if header.startswith("@") and plus.startswith("+"):
                    looks_fastq = True
                seq = seq.rstrip("\n")
                qual = qual.rstrip("\n")
                lengths.append(len(seq))
                for c in qual:
                    o = ord(c)
                    min_q = min(min_q, o)
                    max_q = max(max_q, o)
                n += 1
    except (OSError, EOFError) as exc:
        return {"format": "unreadable", "error": str(exc)}

    if n == 0 or not looks_fastq:
        return {"format": "unknown", "n_reads_sampled": n,
                "error": "did not parse as FASTQ (no @/+ record structure found)"}

    lc = Counter(lengths)
    facts: dict[str, Any] = {
        "format": "fastq",
        "compression": "gzip" if str(path).endswith(".gz") else "none",
        "n_reads_sampled": n,
        "read_length_min": min(lengths),
        "read_length_max": max(lengths),
        "read_length_mode": lc.most_common(1)[0][0],
        "variable_length": len(lc) > 1,
        "encoding_guess": _guess_encoding(min_q, max_q),
        # single vs paired can't be known from one file; onboarding fills layout from filename/user
        "layout": _infer_layout_from_name(path),
    }
    return facts


def _infer_layout_from_name(path: str) -> str:
    """Heuristic: filenames like *_1.fastq / *_R1.fastq suggest one mate of a pair.

    This is a hint only; true SE/PE is a declared fact reconciled in onboarding.
    """
    stem = Path(path).name.lower()
    for token in ("_r1", "_r2", "_1.", "_2."):
        if token in stem:
            return "PE?"        # looks like a mate file — confirm during reconciliation
    return "SE?"
