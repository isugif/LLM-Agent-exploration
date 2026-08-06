"""Deterministic FastQC execution wrapper — the 'compute' layer.

No LLM, no judgment. It runs `fastqc` in a subprocess, captures exit code / stdout / stderr,
and returns a RunResult carrying an AUDIT RECORD (command, tool version, timing, paths). The
audit record is what the diagnosis and evaluation harnesses read after the fact — it is the
trail that makes silent failures investigable.

In the real system this layer is Nextflow (retries, provenance). Here it is a single subprocess
so the four-harness loop stays the focus.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from shared.models import RunResult


def fastqc_version() -> str | None:
    exe = shutil.which("fastqc")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or out.stderr.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_fastqc(fastq_path: str, out_dir: str, threads: int = 1, timeout: int = 600) -> RunResult:
    """Run FastQC on a single FASTQ into out_dir. Returns a RunResult with audit trail."""
    exe = shutil.which("fastqc")
    audit: dict = {
        "tool": "fastqc",
        "tool_version": fastqc_version(),
        "input": str(fastq_path),
        "out_dir": str(out_dir),
    }

    if exe is None:
        return RunResult(
            tool="fastqc", ok=False, exit_code=None, stdout="", stderr="",
            output_dir=None, audit=audit,
            error="fastqc not found on PATH. Install via bioconda: "
                  "`mamba install -c bioconda fastqc`.",
        )

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-t", str(threads), "-o", str(out_dir), str(fastq_path)]
    audit["cmd"] = " ".join(cmd)

    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        audit["seconds"] = round(time.time() - start, 2)
        return RunResult(
            tool="fastqc", ok=False, exit_code=None, stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[timeout after {timeout}s]", output_dir=str(out_dir),
            audit=audit, error="fastqc timed out",
        )
    audit["seconds"] = round(time.time() - start, 2)
    audit["exit_code"] = proc.returncode

    return RunResult(
        tool="fastqc",
        ok=proc.returncode == 0,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        output_dir=str(out_dir),
        audit=audit,
    )
