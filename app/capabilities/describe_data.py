"""describe_data — "what can you tell me about this data".

Deterministic ground truth (always): profile_fastq -> facts + plot distributions. Reconciliation
against the message's declared facts reuses the onboarding harness's DeclaredFacts schema + _reconcile
(honoring the caller-selected provider). The LLM only narrates; with no LLM we emit a templated
summary. Returns {"panel": <dict|None>, "prose": str}.
"""

from __future__ import annotations

from typing import Optional

from shared.probes.fastq_probe import profile_fastq
from langgraph_impl.harnesses.onboarding import DeclaredFacts, _reconcile

# order + friendly labels for the facts table (keys come from shared/probes/fastq_probe.py:probe)
_FACT_LABELS = [
    ("format", "Format"),
    ("compression", "Compression"),
    ("n_reads_sampled", "Reads sampled"),
    ("read_length_min", "Read length (min)"),
    ("read_length_max", "Read length (max)"),
    ("read_length_mode", "Read length (mode)"),
    ("variable_length", "Variable length"),
    ("encoding_guess", "Quality encoding"),
    ("layout", "Layout (hint)"),
]

_NARRATE_SYSTEM = (
    "You are a bioinformatics assistant. In 2-4 sentences, plainly summarize what these MEASURED "
    "facts say about a sequencing file. Only use the facts given; do not invent numbers. If there "
    "are disagreements, call them out as things to double-check."
)


def _facts_rows(facts: dict) -> list[dict]:
    return [{"label": label, "value": facts.get(key)} for key, label in _FACT_LABELS if key in facts]


def _declared(message: str, provider) -> dict:
    if getattr(provider, "name", "null") == "null":
        return {}
    parsed = provider.extract(
        DeclaredFacts,
        system="Extract sequencing metadata the scientist asserts; use 'unknown' when not stated.",
        prompt=message,
    )
    return parsed.model_dump() if parsed is not None else {}


def _narrate(facts: dict, disagreements: list[str], provider) -> str:
    lines = [f"{label}: {facts.get(key)}" for key, label in _FACT_LABELS if key in facts]
    if disagreements:
        lines.append("Disagreements: " + "; ".join(disagreements))
    prose = provider.complete(_NARRATE_SYSTEM, "\n".join(lines))
    if not prose or prose.startswith("[LLM"):          # NullProvider sentinel -> templated summary
        base = (f"This looks like {facts.get('compression','?')}-compressed "
                f"{facts.get('format','?')} data: {facts.get('n_reads_sampled','?')} reads sampled, "
                f"read length {facts.get('read_length_min','?')}–{facts.get('read_length_max','?')} bp "
                f"(mode {facts.get('read_length_mode','?')}), quality encoding "
                f"{facts.get('encoding_guess','?')}, layout hint {facts.get('layout','?')}.")
        if disagreements:
            base += " Double-check: " + "; ".join(disagreements)
        return base
    return prose


def run(message: str, file: Optional[str], provider) -> dict:
    """Profile `file` and return {panel, prose}. `file` may come from the Intent or a UI field."""
    if not file:
        return {"panel": None,
                "prose": "Which FASTQ file should I look at? Give me a path "
                         "(e.g. `shared/data/SRR11140744_10k.fastq.gz`)."}

    prof = profile_fastq(file)
    facts = prof["facts"]
    if facts.get("format") != "fastq":
        err = facts.get("error", "not recognized as FASTQ")
        return {"panel": {"file": file, "error": err},
                "prose": f"I couldn't read `{file}` as FASTQ: {err}"}

    declared = _declared(message, provider)
    disagreements = _reconcile(declared, facts)

    panel = {
        "file": file,
        "facts": _facts_rows(facts),
        "length_hist": prof["length_hist"],
        "qual_by_pos": prof["qual_by_pos"],
        "disagreements": disagreements,
        "declared": {k: v for k, v in declared.items() if v and v != "unknown"},
    }
    return {"panel": panel, "prose": _narrate(facts, disagreements, provider)}
