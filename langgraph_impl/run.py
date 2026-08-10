"""CLI entrypoint for the LangGraph track.

    python -m langgraph_impl.run --fastq <path> --question "..." [--deliverable "..."]

Prints the spec, routing decision, and final verdict as JSON. Identical CLI surface to the NOOA
track (nooa_impl/run.py) so the two can be diffed on the same input.
"""

from __future__ import annotations

import argparse
import json

from langgraph_impl.graph import build_graph
from shared.report import write_outputs


def main() -> None:
    ap = argparse.ArgumentParser(description="Four-harness bioinformatics pipeline (LangGraph track)")
    ap.add_argument("--tool", default="fastqc", help="which tool's contract to route against")
    ap.add_argument("--fastq", required=True, help="input (a FASTQ file, or a report dir for aggregators)")
    ap.add_argument("--reference", default=None, help="genome FASTA for aligners (a second input)")
    ap.add_argument("--question", required=True, help="the scientist's request in plain language")
    ap.add_argument("--deliverable", default=None, help="what they want out (defaults to --question)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    graph = build_graph()
    final = graph.invoke({
        "tool": args.tool,
        "fastq": args.fastq,
        "reference": args.reference,
        "question": args.question,
        "deliverable": args.deliverable or args.question,
        "out_dir": args.out_dir,
    })

    report = {
        "track": "langgraph",
        "tool": args.tool,
        "llm_provider": final.get("llm_provider"),
        "spec": final.get("spec"),
        "route": final.get("route"),
        "run_result": _trim_run(final.get("run_result")),
        "verdict": final.get("verdict"),
    }
    print(json.dumps(report, indent=2))
    # persist report.json + report_summary.md into the output dir (the run's own dir)
    out_dir = final.get("out_dir") or args.out_dir
    if out_dir:
        write_outputs(report, out_dir)


def _trim_run(rr):
    """Drop noisy stdout/stderr from the printed report; keep the audit + exit code."""
    if not rr:
        return None
    return {k: v for k, v in rr.items() if k not in ("stdout", "stderr")}


if __name__ == "__main__":
    main()
