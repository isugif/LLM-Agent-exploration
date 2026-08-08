"""Tool-type taxonomy + classifier — our clean-model port of the skill's patterns.md (R0).

The skill classifies every tool into T1-T5 and uses that to pick reference anchors and section shapes
(demos.md). We keep the same five types (renamed for readability) and the same deterministic
precedence, but the detection is data (keyword signals), tool-agnostic — no hardcoded tool names,
which was a smell in the original bash checkers.

    T1 single_command     — one primary command, no subcommands            (e.g. fastqc)
    T2 subcommand_toolkit — `tool <subcommand> ...`, lists modules         (e.g. samtools)
    T3 helper             — post-processes other tools' outputs            (e.g. sort/convert utils)
    T4 aggregator         — scans heterogeneous outputs -> one report      (e.g. multiqc)
    T5 multi_step         — build-index-then-run / multi-stage             (e.g. hisat2, star)

Precedence (patterns.md R0A): T4 > T2 > T5 > T3 > T1 — stronger schema/branching constraints win.
"""

from __future__ import annotations

# ordered by R0A precedence; first match wins
TYPES = ["aggregator", "subcommand_toolkit", "multi_step", "helper", "single_command"]

# keyword signals per type (checked against the tool's --help / docs source, lowercased)
_SIGNALS = {
    "aggregator": ["aggregate", "aggregates", "across samples", "multiple samples", "multiple tools",
                   "dashboard", "consolidat", "summarize analysis", "scan", "report across",
                   "single report"],
    "subcommand_toolkit": ["commands:", "sub-command", "subcommand", "available commands",
                           "<command>", "usage:   <command>", "modules:"],
    "multi_step": ["-build", "build index", "genome index", "-x <", "reference genome index",
                   "two-step", "first build", "index must be built"],
    # helper (T3) = a tool whose PURPOSE is post-processing other tools' outputs. Keep signals
    # purpose-specific: merely ACCEPTING bam/sam as an input (as fastqc does) must NOT match.
    "helper": ["mark duplicates", "post-processing", "post-process", "convert between",
               "converts between", "sort, index", "sorts and indexes", "downstream of"],
}


def classify(source_text: str) -> str:
    """Return the tool type from its source text, honoring R0A precedence.

    Deterministic and cheap (no LLM). An LLM tie-breaker can be layered on later for ambiguous
    tools; source evidence remains authoritative (patterns.md R0B).
    """
    t = (source_text or "").lower()
    for tool_type in TYPES:                       # TYPES is already in precedence order
        signals = _SIGNALS.get(tool_type, [])
        if any(sig in t for sig in signals):
            return tool_type
    return "single_command"


def describe(tool_type: str) -> str:
    return {
        "single_command": "one primary command, no subcommands",
        "subcommand_toolkit": "`tool <subcommand> ...`; lists modules/commands",
        "helper": "post-processes other tools' outputs (sort/convert/filter/index)",
        "aggregator": "scans heterogeneous outputs into one report",
        "multi_step": "build-index-then-run / multi-stage pipeline",
    }.get(tool_type, tool_type)
