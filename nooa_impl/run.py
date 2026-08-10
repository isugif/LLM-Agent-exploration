"""CLI entrypoint for the NOOA track. Identical surface to the LangGraph track.

    python -m nooa_impl.run --fastq <path> --question "..." [--deliverable "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import json

from nooa_impl.orchestrator import run_pipeline
from shared.report import write_outputs


def main() -> None:
    ap = argparse.ArgumentParser(description="Four-harness bioinformatics pipeline (NOOA track)")
    ap.add_argument("--tool", default="fastqc", help="which tool's contract to route against")
    ap.add_argument("--fastq", required=True, help="input (a FASTQ file, or a report dir for aggregators)")
    ap.add_argument("--reference", default=None, help="genome FASTA for aligners (a second input)")
    ap.add_argument("--gtf", "--annotation", dest="annotation", default=None,
                    help="GTF annotation for RNA-seq QC (rustqc; a second input)")
    ap.add_argument("--question", required=True, help="the scientist's request in plain language")
    ap.add_argument("--deliverable", default=None, help="what they want out (defaults to --question)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    report = asyncio.run(run_pipeline(args.fastq, args.question, args.deliverable, args.out_dir,
                                      tool_id=args.tool, reference=args.reference,
                                      annotation=args.annotation))
    print(json.dumps(report, indent=2))
    out_dir = report.get("out_dir") or args.out_dir
    if out_dir:
        write_outputs(report, out_dir)


if __name__ == "__main__":
    main()
