"""Tool registry — the one thing that stays per-tool code: the output parser.

Everything else about a tool is data (its `contract.yml`): how to run it (execution.argv), its
preconditions, boundaries, failure modes, and which metrics to score (the expectation table). But
every tool writes its results in its own format, so turning an output directory into a metric dict
is inherently tool-specific code.

Adding a tool therefore means: drop `bio-tools/<tool>/contract.yml` (data) + write one parser and
register it here (code). No harness changes.

A parser has the signature:  parse(output_dir: str) -> dict[str, Any]
It returns a flat dict of metric_name -> value; metrics named in the tool's expectation table are
scored by the evaluation harness. Return {"error": "..."} if the output can't be parsed.
"""

from __future__ import annotations

from typing import Callable

from shared.parsers.fastqc_parse import parse_fastqc
from shared.parsers.multiqc_parse import parse_multiqc
from shared.parsers.minimap2_parse import parse_minimap2
from shared.parsers.seqkit_parse import parse_seqkit
from shared.parsers.rustqc_parse import parse_rustqc
from shared.parsers.samtools_bam_parse import parse_bam_transform
from shared.probes.fastq_probe import probe as probe_fastq
from shared.probes.report_dir_probe import probe_report_dir
from shared.probes.aln_probe import probe_alignment

Fn = Callable[[str], dict]

# Output parser: output_dir -> {metric: value}. One per tool (each tool emits differently).
PARSERS: dict[str, Fn] = {
    "fastqc": parse_fastqc,
    "multiqc": parse_multiqc,
    "minimap2": parse_minimap2,
    "hisat2": parse_minimap2,          # writes {out_dir}/aln.sam — the generic SAM parser handles it
    "seqkit": parse_seqkit,
    "rustqc": parse_rustqc,
    "samtools_sort": parse_bam_transform,
    "samtools_markdup": parse_bam_transform,
}

# Input probe: input_path -> measured facts. Keyed by input TYPE, shared across tools that take
# the same input. fastqc/minimap2 take a FASTQ (default probe); multiqc takes a directory of reports.
PROBES: dict[str, Fn] = {
    "fastqc": probe_fastq,
    "multiqc": probe_report_dir,
    # alignment-consuming tools probe a BAM/SAM/CRAM instead of a FASTQ
    "rustqc": probe_alignment,
    "samtools_sort": probe_alignment,
    "samtools_markdup": probe_alignment,
}


def get_parser(tool_id: str) -> Fn:
    if tool_id not in PARSERS:
        raise KeyError(
            f"no parser registered for tool '{tool_id}'. "
            f"Add one in shared/tools/registry.py. Known: {sorted(PARSERS)}"
        )
    return PARSERS[tool_id]


def parse_output(tool_id: str, out_dir: str) -> dict:
    """Parse a tool's output, or return an {'error': ...} dict when no parser is registered.

    Lets the evaluation harness say 'cannot_assess' for a reviewed-but-not-yet-parsed tool (e.g. a
    freshly HRR'd tool) instead of crashing — the right-to-refuse, not a stack trace."""
    fn = PARSERS.get(tool_id)
    if fn is None:
        return {"error": f"no output parser registered for '{tool_id}'; its result cannot be scored yet"}
    return fn(out_dir)


def get_probe(tool_id: str) -> Fn:
    """Return the input probe for a tool. Defaults to the FASTQ probe."""
    return PROBES.get(tool_id, probe_fastq)
