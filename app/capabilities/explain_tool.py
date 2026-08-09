"""explain_tool — answer questions about a documented tool from its curated workbook (RAG).

Retrieves the tool's clean sections (bio-tools/<tool>/{manifest,clean/*}.yml), renders the key facts
(summary, usage, options/parameters, off-label boundaries, citation) into the panel, AND asks the LLM
to answer the user's specific question grounded ONLY in those sections. This is the "talk over the
contract" capability — the corpus is the curator's output.

Unreviewed machine sections (still carrying HRR_ placeholders) are skipped so we never present
placeholders as facts.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

import yaml

from shared import contracts_lib as cl
from curator.stages.provision import _resolve_binary, ENV as CURATOR_ENV
from curator.references import sourcing

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "bio-tools"

# Context budgets (chars) — keep the whole prompt comfortably inside a small local model's window.
# These caps ARE the "lazy loading": we include bounded slices, prioritizing the authoritative --help,
# and keep only the most recent conversation turns (a sliding window).
HELP_CAP = 5000
DOCS_CAP = 2500
HIST_CAP = 1500

RAG_SYSTEM = (
    "You are a bioinformatics assistant. Answer the user's MOST RECENT underlying request, using the "
    "whole conversation to resolve what they mean — e.g. a short reply that only names a tool "
    "continues the earlier question (do not restart with a generic overview). Treat the tool's "
    "`--help` as the SOURCE OF TRUTH for flags/parameters, and the curated documentation for context. "
    "Name exact flags. If a flag or behavior is NOT present in the provided --help or documentation, "
    "say you don't see it in the tool's help — do NOT guess or invent a flag name, default, or option."
)


def _live_help(tool: str) -> str:
    """The tool's real `--help`, from the curator-tools env if installed there, else the system PATH.
    Empty string if the tool isn't available (we don't auto-install on a question)."""
    try:
        binj = _resolve_binary(tool)                 # installed in the curator-tools env?
        if binj:
            return sourcing.source_from_help(binj, env=CURATOR_ENV)
        if shutil.which(tool):
            return sourcing.source_from_help(tool, env=None)
    except Exception:                                # noqa: BLE001
        pass
    return ""


_ANSI = re.compile(r"\x1b\[[0-9;]*m")               # color codes
_BOX = " \t│|┃╎┆╷╵"                                 # rich-click table borders + whitespace
_FLAG = re.compile(r"-{1,2}[A-Za-z0-9]")            # an option token at the start of the cleaned line


def _help_flags(help_text: str) -> str:
    """The option-defining lines of `--help` (compact + complete), so a flag is never dropped by a
    positional truncation. Tolerates rich-click box borders + ANSI (multiqc-style) and plain help
    (fastqc-style). This is the 'chunk what's relevant' step for parameter questions."""
    out = []
    for ln in help_text.splitlines():
        s = _ANSI.sub("", ln).strip().strip(_BOX).strip()
        if _FLAG.match(s):
            out.append(s)
    return "\n".join(out)


def _history_text(history: Optional[list[dict]], cap: int = HIST_CAP) -> str:
    """Most-recent conversation turns as text, tail-trimmed to `cap` chars (sliding window)."""
    if not history:
        return ""
    lines = [f"{t.get('role', 'user')}: {(t.get('content') or '').strip()}"
             for t in history if (t.get('content') or '').strip()]
    return "\n".join(lines)[-cap:]


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


def _answer(message: str, tool: str, wb: dict, provider, history: Optional[list[dict]]) -> str:
    if getattr(provider, "name", "null") == "null":           # deterministic fallback
        summary = (wb["sections"].get("meta", {}) or {}).get("summary", "")
        return (summary or f"See the {tool} documentation panel on the right.").strip()

    # Include the current message IN the conversation so a one-word disambiguation ("fastqc") keeps
    # the earlier question in scope, rather than becoming the whole question.
    convo = list(history or []) + [{"role": "user", "content": message}]
    parts = ["Conversation so far:\n" + _history_text(convo, cap=2200)]
    parts.append(f"Tool: {tool}")
    help_text = _live_help(tool)
    if help_text:
        flags = _help_flags(help_text)                # flags first (complete), then some prose
        help_ctx = (f"All flags:\n{flags[:3500]}\n\n{help_text[:1500]}") if flags else help_text[:HELP_CAP]
        parts.append(f"Authoritative `{tool} --help` (source of truth for flags):\n{help_ctx}")
    parts.append("Curated documentation:\n" + _context(wb)[:DOCS_CAP])
    return provider.complete(RAG_SYSTEM, "\n\n".join(parts))


def run(message: str, tool: str, provider, history: Optional[list[dict]] = None) -> dict:
    """Answer a question about `tool` from its workbook + live --help. Returns {panel, prose}."""
    wb = load_workbook(tool)
    if wb is None:
        others = ", ".join(available_tools()) or "(none yet)"
        return {"panel": None,
                "prose": f"I don't have a documented workbook for **{tool}** yet. You can add it with "
                         f"\"install {tool}\". Documented tools: {others}."}
    return {"panel": _panel(tool, wb), "prose": _answer(message, tool, wb, provider, history)}
