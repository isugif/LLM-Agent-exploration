"""Generic, contract-driven tool runner — replaces the per-tool fastqc_runner.

A tool's `contract.yml` declares how to invoke it:

    execution:
      argv: [fastqc, -t, "{threads}", -o, "{out_dir}", "{input}"]
      version_argv: [fastqc, --version]
      install_hint: "mamba install -c bioconda fastqc"

`run_tool` renders those placeholders token-by-token and runs the tool with a LIST of args
(`subprocess.run([...])`, never `shell=True`), so there is no shell-injection surface even though
the command comes from data. It returns the shared `RunResult` with an audit record — the trail the
diagnosis/evaluation harnesses read afterwards.

This is the "runner is generic, only the parser is per-tool" split: adding a tool needs a
`contract.yml` (data) + a parser (code), not a new runner.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from shared.models import RunResult


def _render(argv: list[str], subs: dict[str, str]) -> list[str]:
    """Substitute {placeholders} in each token independently. Non-placeholder tokens pass through."""
    out = []
    for tok in argv:
        for key, val in subs.items():
            tok = tok.replace("{" + key + "}", str(val))
        out.append(tok)
    return out


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _unfilled_placeholder(argv: list[str]) -> str | None:
    """The name of the first still-unfilled {placeholder} in a rendered argv, or None."""
    for tok in argv:
        m = _PLACEHOLDER.search(tok)
        if m:
            return m.group(1)
    return None


def _tool_version(version_argv: list[str] | None) -> str | None:
    if not version_argv:
        return None
    exe = shutil.which(version_argv[0])
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *version_argv[1:]], capture_output=True, text=True, timeout=30)
        return (out.stdout.strip() or out.stderr.strip()) or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# friendly name for an unfilled secondary-input placeholder, for a clear "you didn't provide X" error
_INPUT_LABEL = {"reference": "a reference genome (FASTA)", "annotation": "a GTF annotation"}


def run_tool(contract: dict, input_path: str, out_dir: str, *,
             inputs: dict | None = None, threads: int = 1, timeout: int = 600) -> RunResult:
    """Run the tool described by `contract` on `input_path` into `out_dir`.

    `inputs` supplies EXTRA named placeholder substitutions for tools that take more than one input
    — e.g. `{"reference": genome.fa}` for an aligner, `{"annotation": genes.gtf}` for rustqc. Single-
    input tools ignore it. A tool whose argv needs `{name}` but got none fails cleanly (the unfilled
    placeholder is caught before launch), so the judgment harness's precondition is the real gate —
    this is only a backstop.
    """
    tool_id = contract["id"]
    ex = contract.get("execution", {})
    argv_template = ex.get("argv")
    install_hint = ex.get("install_hint", f"install {tool_id}")
    inputs = {k: v for k, v in (inputs or {}).items() if v}   # drop None/empty extra inputs

    audit: dict = {
        "tool": tool_id,
        "tool_version": _tool_version(ex.get("version_argv")),
        "input": str(input_path),
        "out_dir": str(out_dir),
        **{k: str(v) for k, v in inputs.items()},
    }

    if not argv_template:
        return RunResult(tool=tool_id, ok=False, exit_code=None, stdout="", stderr="",
                         output_dir=None, audit=audit,
                         error=f"contract for '{tool_id}' has no execution.argv")

    exe = shutil.which(argv_template[0])
    if exe is None:
        return RunResult(tool=tool_id, ok=False, exit_code=None, stdout="", stderr="",
                         output_dir=None, audit=audit,
                         error=f"{argv_template[0]} not found on PATH. Install: {install_hint}")

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    subs = {"input": input_path, "out_dir": out_dir, "threads": threads, **inputs}
    argv = _render(argv_template, subs)
    unfilled = _unfilled_placeholder(argv)               # a required secondary input wasn't supplied
    if unfilled:
        label = _INPUT_LABEL.get(unfilled, f"the '{unfilled}' input")
        return RunResult(tool=tool_id, ok=False, exit_code=None, stdout="", stderr="",
                         output_dir=None, audit=audit,
                         error=f"{tool_id} requires {label}; none was provided")
    argv[0] = exe                       # use the resolved absolute path
    audit["cmd"] = " ".join(argv)

    start = time.time()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        audit["seconds"] = round(time.time() - start, 2)
        return RunResult(tool=tool_id, ok=False, exit_code=None, stdout=exc.stdout or "",
                         stderr=(exc.stderr or "") + f"\n[timeout after {timeout}s]",
                         output_dir=str(out_dir), audit=audit, error=f"{tool_id} timed out")
    audit["seconds"] = round(time.time() - start, 2)
    audit["exit_code"] = proc.returncode

    return RunResult(tool=tool_id, ok=proc.returncode == 0, exit_code=proc.returncode,
                     stdout=proc.stdout, stderr=proc.stderr, output_dir=str(out_dir), audit=audit)
