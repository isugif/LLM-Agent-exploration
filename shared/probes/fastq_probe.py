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
                # rstrip \r too: a CRLF file would otherwise leave \r (13) in the quality
                # range and force encoding_guess to "unknown"
                seq = seq.rstrip("\r\n")
                qual = qual.rstrip("\r\n")
                lengths.append(len(seq))
                if qual:
                    qb = qual.encode("latin-1", errors="replace")   # bytes min/max, no per-char ord()
                    min_q = min(min_q, min(qb))
                    max_q = max(max_q, max(qb))
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


def profile_fastq(path: str, sample_reads: int = 10000) -> dict[str, Any]:
    """Richer profile for the UI: the ground-truth facts plus two plottable distributions.

    Returns {"facts": <probe() output>, "length_hist": {len: count}, "qual_by_pos": [mean_q, ...]}.
    Pure stdlib, sampled — same cost class as probe(). Non-FASTQ inputs yield empty distributions.
    """
    facts = probe(path, sample_reads=sample_reads)
    if facts.get("format") != "fastq":
        return {"facts": facts, "length_hist": {}, "qual_by_pos": []}

    offset = 64 if facts.get("encoding_guess") == "phred64" else 33
    length_hist: Counter = Counter()
    pos_sum: list[int] = []
    pos_cnt: list[int] = []
    n = 0
    with _open(path) as fh:
        while n < sample_reads:
            header = fh.readline()
            if not header:
                break
            seq = fh.readline()
            fh.readline()                        # '+' separator
            qual = fh.readline()
            if not qual:
                break
            seq = seq.rstrip("\r\n")
            qual = qual.rstrip("\r\n")
            length_hist[len(seq)] += 1
            for i, c in enumerate(qual):
                if i >= len(pos_sum):
                    pos_sum.append(0)
                    pos_cnt.append(0)
                pos_sum[i] += ord(c) - offset
                pos_cnt[i] += 1
            n += 1

    qual_by_pos = [round(s / c, 2) if c else 0.0 for s, c in zip(pos_sum, pos_cnt)]
    return {
        "facts": facts,
        "length_hist": {int(k): int(v) for k, v in sorted(length_hist.items())},
        "qual_by_pos": qual_by_pos,
    }


def _infer_layout_from_name(path: str) -> str:
    """Heuristic: filenames like *_1.fastq / *_R1.fastq suggest one mate of a pair.

    This is a hint only; true SE/PE is a declared fact reconciled in onboarding.
    """
    stem = Path(path).name.lower()
    for token in ("_r1", "_r2", "_1.", "_2."):
        if token in stem:
            return "PE?"        # looks like a mate file — confirm during reconciliation
    return "SE?"
