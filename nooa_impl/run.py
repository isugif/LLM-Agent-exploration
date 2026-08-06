"""CLI entrypoint for the NOOA track. Identical surface to the LangGraph track.

    python -m nooa_impl.run --fastq <path> --question "..." [--deliverable "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import json

from nooa_impl.orchestrator import run_pipeline


def main() -> None:
    ap = argparse.ArgumentParser(description="Four-harness FastQC pipeline (NOOA track)")
    ap.add_argument("--fastq", required=True)
    ap.add_argument("--question", required=True, help="the scientist's request in plain language")
    ap.add_argument("--deliverable", default=None, help="what they want out (defaults to --question)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    report = asyncio.run(run_pipeline(args.fastq, args.question, args.deliverable, args.out_dir))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
