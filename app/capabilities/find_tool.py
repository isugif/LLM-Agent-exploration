"""find_tool — cross-tool discovery: "which tool is good for alignment / takes fastq".

The counterpart to explain_tool: explain_tool answers about ONE named tool; find_tool answers a
question with NO tool named, by retrieving over the whole catalog (shared/catalog.py).

Structured-first, LLM-fallback (the repo's deterministic-first philosophy):
  1. deterministic filter — map the message to a category (synonyms) and/or an input format, then
     `catalog.find(...)`. Exact, citable, works offline.
  2. if nothing structured matched, ask the LLM to pick from the catalog — grounded ONLY in the
     records shown, and told to say so when nothing fits (never invent a tool).

Returns {"panel": {kind: 'catalog', ...} | None, "prose": str}.
"""

from __future__ import annotations

import re
from typing import Optional

from shared import catalog
from shared.knowledge.categories import category_from_text, CATEGORIES

# input formats we recognize in a free-text question ("which tool takes fastq/bam/...").
_FORMATS = ("fastq", "fasta", "bam", "sam", "cram", "vcf", "bcf", "gff", "gtf", "bed", "report_dir")
_FORMAT_RE = re.compile(r"\b(" + "|".join(_FORMATS) + r")\b", re.IGNORECASE)

RAG_SYSTEM = (
    "You help a scientist pick a bioinformatics tool. Recommend ONLY from the catalog provided "
    "below — never name a tool that is not in it. If none of the catalog tools fit the request, say "
    "so plainly and suggest adding one. Name the tool(s), say in one line why each fits, and keep it "
    "to a few sentences. Do not invent flags, formats, or capabilities."
)


def _format_in(message: str) -> Optional[str]:
    m = _FORMAT_RE.search(message or "")
    return m.group(1).lower() if m else None


def _panel(records: list[dict], category: Optional[str], input_format: Optional[str]) -> dict:
    return {
        "kind": "catalog",
        "query": {"category": category, "input_format": input_format},
        "count": len(records),
        "tools": [{
            "tool": r["tool"],
            "summary": r["summary"],
            "categories": r["category_tags"],
            "input_formats": r["input_formats"],
            "output_formats": r["output_formats"],
            "reviewed": r["reviewed"],
        } for r in records],
    }


def _catalog_text(records: list[dict]) -> str:
    """Compact catalog rendering for the LLM (grounding context)."""
    lines = []
    for r in records:
        cats = ", ".join(r["category_tags"]) or "uncategorized"
        ins = ", ".join(r["input_formats"]) or "?"
        lines.append(f"- {r['tool']}: {r['summary'] or '(no summary)'} "
                     f"[purpose: {cats}; input: {ins}]")
    return "\n".join(lines)


def _deterministic_prose(records: list[dict], category: Optional[str],
                         input_format: Optional[str]) -> str:
    names = ", ".join(f"**{r['tool']}**" for r in records)
    if category and input_format:
        crit = f"in {category.replace('_', ' ')} that take {input_format}"
    elif category:
        crit = f"in {category.replace('_', ' ')}"
    elif input_format:
        crit = f"that take {input_format} input"
    else:
        crit = "matching your request"
    return f"Documented tools {crit}: {names}. Ask \"tell me about {records[0]['tool']}\" for details."


def run(message: str, provider) -> dict:
    """Answer a cross-tool question. `provider` may be a NullProvider (offline) — still works."""
    category = category_from_text(message)
    input_format = _format_in(message)

    # 1) structured filter (deterministic)
    if category or input_format:
        hits = catalog.find(category=category, input_format=input_format)
        if hits:
            return {"panel": _panel(hits, category, input_format),
                    "prose": _deterministic_prose(hits, category, input_format)}
        # a clear constraint that matched nothing — say so, don't fall through to a fuzzy guess
        what = category.replace("_", " ") if category else f"{input_format} input"
        return {"panel": _panel([], category, input_format),
                "prose": f"I don't have a documented tool for **{what}** yet. "
                         f"You can add one with \"install <tool>\"."}

    # 2) no structured constraint — LLM over the whole catalog, grounded; offline: list everything
    records = catalog.catalog()
    if not records:
        return {"panel": None, "prose": "No tools are documented yet. Add one with \"install <tool>\"."}
    if getattr(provider, "name", "null") == "null":
        return {"panel": _panel(records, None, None),
                "prose": "I can match tools by input format or purpose — try \"which tool takes "
                         "fastq?\" or \"which tool is good for alignment?\". "
                         f"Purpose categories: {', '.join(c.replace('_', ' ') for c in CATEGORIES[:6])}, …"}
    prose = provider.complete(RAG_SYSTEM,
                              f"Catalog:\n{_catalog_text(records)}\n\nUser question: {message}")
    return {"panel": _panel(records, None, None), "prose": prose}
