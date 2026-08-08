"""explain_tool — answer questions about a documented tool from its curated workbook (RAG).

Retrieves the tool's clean sections (bio-tools/<tool>/{manifest,clean/*}.yml), renders the key facts
(summary, usage, options/parameters, off-label boundaries, citation) into the panel, AND asks the LLM
to answer the user's specific question grounded ONLY in those sections. This is the "talk over the
contract" capability — the corpus is the curator's output.

Unreviewed machine sections (still carrying HRR_ placeholders) are skipped so we never present
placeholders as facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from shared import contracts_lib as cl

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "bio-tools"

RAG_SYSTEM = (
    "You are a bioinformatics assistant. Answer the user's question about the tool USING ONLY the "
    "provided documentation sections. Be concise and specific — name exact flags when relevant. If "
    "the answer is not in the documentation, say so plainly; never invent flags, defaults, or behavior."
)


def available_tools() -> list[str]:
    if not TOOLS.exists():
        return []
    return sorted(p.name for p in TOOLS.iterdir() if (p / "manifest.yml").exists())


def _has_hrr(obj) -> bool:
    return "HRR_" in yaml.safe_dump(obj, allow_unicode=True)


def load_workbook(tool: str) -> Optional[dict]:
    """Load a tool's manifest + clean sections. Returns None if the tool has no workbook."""
    man = TOOLS / tool / "manifest.yml"
    if not man.exists():
        return None
    m = yaml.safe_load(man.read_text())
    sections = {}
    for ref in m.get("sections", []):
        p = TOOLS / tool / ref["path"]
        if p.exists():
            sections[ref["name"]] = yaml.safe_load(p.read_text())
    reviewed = False
    try:
        reviewed = cl.is_reviewed(cl.load_contract(tool))
    except Exception:                          # noqa: BLE001
        pass
    return {"tool": tool, "version": m.get("version"), "sections": sections, "reviewed": reviewed}


def _panel(tool: str, wb: dict) -> dict:
    s = wb["sections"]

    def ok(name):                              # section present and not an HRR_ placeholder
        v = s.get(name)
        return v if (v is not None and not _has_hrr(v)) else None

    meta = ok("meta") or {}
    usage = ok("usage") or {}
    options = ok("options") or {}
    mnu = ok("must_not_use") or []
    citations = ok("citations") or {}
    return {
        "kind": "tool",
        "tool": tool,
        "version": wb.get("version"),
        "reviewed": wb.get("reviewed"),
        "summary": (meta.get("summary") or "").strip(),
        "usage": usage.get("examples", []),
        "options": options.get("options", []),
        "boundaries": [(b.get("boundary") or "").strip() for b in mnu],
        "citation": citations.get("doi") or citations.get("url"),
    }


def _context(wb: dict) -> str:
    """Compact text rendering of the reviewed sections, for the LLM (RAG context)."""
    parts = []
    for name, val in wb["sections"].items():
        if _has_hrr(val):                      # skip unreviewed machine placeholders
            continue
        parts.append(f"## {name}\n{yaml.safe_dump(val, sort_keys=False, allow_unicode=True).strip()}")
    return "\n\n".join(parts)[:8000]


def _answer(message: str, tool: str, wb: dict, provider) -> str:
    if getattr(provider, "name", "null") == "null":           # deterministic fallback
        summary = (wb["sections"].get("meta", {}) or {}).get("summary", "")
        return (summary or f"See the {tool} documentation panel on the right.").strip()
    return provider.complete(RAG_SYSTEM,
                             f"Tool: {tool}\n\nDocumentation:\n{_context(wb)}\n\nQuestion: {message}")


def run(message: str, tool: str, provider) -> dict:
    """Answer a question about `tool` from its workbook. Returns {panel, prose}."""
    wb = load_workbook(tool)
    if wb is None:
        others = ", ".join(available_tools()) or "(none yet)"
        return {"panel": None,
                "prose": f"I don't have a documented workbook for **{tool}** yet. You can add it with "
                         f"\"install {tool}\". Documented tools: {others}."}
    return {"panel": _panel(tool, wb), "prose": _answer(message, tool, wb, provider)}
