"""Stdio MCP server exposing the harness (Phase A: spike + the self-guarding gate).

Run:  conda run -n nooa python -m mcp_server.server        (stdio; for a client to spawn)
      conda run -n nooa mcp dev mcp_server/server.py        (interactive inspector, mcp[cli])

Tool surface (and ONLY this surface — no shell, no arbitrary code, no writes outside a run's
out_dir):

  read-only context : probe_data, list_catalog, explain_tool, find_tool
  the gate          : onboard_experiment, judge, run_tool (self-guarding), evaluate_output,
                      diagnose_failure

`run_tool` is the make-or-break piece: it runs onboard -> judge -> (refuse | execute -> evaluate |
diagnose) itself via shared/pipeline.py and returns the full trace, so a client cannot skip the
refusal gate even if it never calls `judge`. `judge`/`onboard_experiment`/`evaluate_output`/
`diagnose_failure` are exposed separately only for transparency.

Every tool returns structured data (dicts) and lets the CLIENT narrate — the server never depends on
an LLM being reachable (deterministic core degrades gracefully via NullProvider).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# Allow `python -m mcp_server.server` and `mcp dev mcp_server/server.py` alike.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from shared import catalog as catalog_lib
from shared import pipeline
from shared.harnesses.onboarding import onboard
from shared.harnesses.judgment import judge as _judge
from shared.harnesses.evaluation import evaluate as _evaluate
from shared.harnesses.diagnosis import diagnose as _diagnose
from shared.probes.fastq_probe import probe as _fastq_probe
from shared.probes.aln_probe import probe_alignment as _aln_probe
from shared.probes.report_dir_probe import probe_report_dir as _report_dir_probe
from shared.llm.provider import NullProvider

server = MCPServer(
    name="bio-harness",
    instructions=(
        "Bioinformatics harness. Use probe_data / list_catalog / explain_tool / find_tool to gather "
        "facts and pick a tool. To RUN anything, call run_tool — it self-guards (onboarding + "
        "judgment) and may refuse. Never assume a run is allowed; read run_tool's returned trace."
    ),
)


def _probe_path(path: str) -> dict[str, Any]:
    """Dispatch to the right probe by content: a directory -> report-dir; .bam/.sam/.cram ->
    alignment; otherwise FASTQ."""
    if os.path.isdir(path):
        return _report_dir_probe(path)
    if path.lower().endswith((".bam", ".sam", ".cram")):
        return _aln_probe(path)
    return _fastq_probe(path)


# --- read-only context ---------------------------------------------------------

@server.tool(description="Measured facts about a data path (FASTQ file, alignment, or report dir). "
                         "Read-only; no interpretation.")
def probe_data(path: str) -> dict[str, Any]:
    return {"path": path, "facts": _probe_path(path)}


@server.tool(description="List/filter the documented tool catalog. All args optional.")
def list_catalog(category: Optional[str] = None, input_format: Optional[str] = None,
                 text: Optional[str] = None) -> dict[str, Any]:
    if category or input_format or text:
        records = catalog_lib.find(category=category, input_format=input_format, text=text)
    else:
        records = catalog_lib.catalog()
    return {"tools": records}


@server.tool(description="Curated facts about one documented tool (summary, usage, options, "
                         "off-label boundaries, citation). Deterministic; the client narrates.")
def explain_tool(tool: str) -> dict[str, Any]:
    from app.capabilities import explain_tool as cap
    out = cap.run(message=f"explain {tool}", tool=tool, provider=NullProvider())
    return {"panel": out.get("panel")}


@server.tool(description="Find candidate tools for a natural-language need (deterministic catalog "
                         "search).")
def find_tool(query: str) -> dict[str, Any]:
    from app.capabilities import find_tool as cap
    out = cap.run(message=query, provider=NullProvider())
    return {"panel": out.get("panel")}


# --- the gate ------------------------------------------------------------------

@server.tool(description="Build the experiment spec for a file: probe measured facts, extract "
                         "declared facts from the question, reconcile, and return disagreements. "
                         "(Single-file; multi-file experiment documents are a later phase.)")
def onboard_experiment(tool: str, path: str, question: str, reference: Optional[str] = None,
                       annotation: Optional[str] = None,
                       provider: Optional[str] = None) -> dict[str, Any]:
    return onboard(tool=tool, fastq=path, question=question, reference=reference,
                   annotation=annotation, provider_name=provider)


@server.tool(description="Judge a spec against a tool's contract (HRR gate + preconditions + "
                         "boundaries). Returns a route with the right to REFUSE. For transparency; "
                         "run_tool judges internally regardless.")
def judge(tool: str, spec: dict[str, Any], provider: Optional[str] = None) -> dict[str, Any]:
    return _judge(tool=tool, spec=spec, llm_provider=provider)


@server.tool(description="THE execution entrypoint. Self-guarding: runs onboarding -> judgment -> "
                         "(refuse | execute -> evaluate | diagnose) and returns the full trace. A "
                         "refusal means nothing was executed. This is the only way to run a tool.")
def run_tool(tool: str, path: str, question: Optional[str] = None, reference: Optional[str] = None,
             annotation: Optional[str] = None, out_dir: Optional[str] = None,
             provider: Optional[str] = None) -> dict[str, Any]:
    return pipeline.run_pipeline(tool=tool, fastq=path, question=question, reference=reference,
                                 annotation=annotation, out_dir=out_dir, provider=provider)


@server.tool(description="Score a completed run's output directory against the tool's expectation "
                         "table. Refuses with 'cannot_assess' if output can't be parsed.")
def evaluate_output(tool: str, out_dir: str, provider: Optional[str] = None) -> dict[str, Any]:
    run_result = {"output_dir": out_dir, "ok": True}
    return _evaluate(tool=tool, run_result=run_result, spec={"declared": {}}, llm_provider=provider)


@server.tool(description="Diagnose a hard failure: match the crash's stderr/stdout/error against the "
                         "tool's known failure_modes; escalate novel crashes.")
def diagnose_failure(tool: str, stderr: str = "", stdout: str = "", error: Optional[str] = None,
                     exit_code: Optional[int] = 1) -> dict[str, Any]:
    run_result = {"stderr": stderr, "stdout": stdout, "error": error, "exit_code": exit_code}
    return _diagnose(tool=tool, run_result=run_result)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
