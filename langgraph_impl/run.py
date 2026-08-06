"""CLI entrypoint for the LangGraph track.

    python -m langgraph_impl.run --fastq <path> --question "..." [--deliverable "..."]

Prints the spec, routing decision, and final verdict as JSON. Identical CLI surface to the NOOA
track (nooa_impl/run.py) so the two can be diffed on the same input.
"""

from __future__ import annotations

import argparse
import json

from langgraph_impl.graph import build_graph


def main() -> None:
    ap = argparse.ArgumentParser(description="Four-harness FastQC pipeline (LangGraph track)")
    ap.add_argument("--fastq", required=True)
    ap.add_argument("--question", required=True, help="the scientist's request in plain language")
    ap.add_argument("--deliverable", default=None, help="what they want out (defaults to --question)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    graph = build_graph()
    final = graph.invoke({
        "fastq": args.fastq,
        "question": args.question,
        "deliverable": args.deliverable or args.question,
        "out_dir": args.out_dir,
    })

    report = {
        "track": "langgraph",
        "llm_provider": final.get("llm_provider"),
        "spec": final.get("spec"),
        "route": final.get("route"),
        "run_result": _trim_run(final.get("run_result")),
        "verdict": final.get("verdict"),
    }
    print(json.dumps(report, indent=2))


def _trim_run(rr):
    """Drop noisy stdout/stderr from the printed report; keep the audit + exit code."""
    if not rr:
        return None
    return {k: v for k, v in rr.items() if k not in ("stdout", "stderr")}


if __name__ == "__main__":
    main()
