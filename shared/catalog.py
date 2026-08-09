"""Tool catalog — one compact, queryable record per documented tool.

Aggregates what's already in each `bio-tools/<tool>/` workbook (manifest + clean sections) into a
flat record the chat's find_tool retriever filters over: purpose (category_tags), what it eats
(input_formats), what it emits (output_formats), and whether its contract is vetted. Purely
deterministic and framework-agnostic (no curator/harness import), so the judgment "retrieve &
match" step can reuse the same catalog later — build once, use twice.

Category precedence: a tool's own `meta.category_tags` wins; otherwise the seed table
(shared/knowledge/categories.py, from the curated tool_categories.tsv) supplies a fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from shared import contracts_lib as cl
from shared.knowledge.categories import seed_category

TOOLS_ROOT = Path(__file__).parent.parent / "bio-tools"


def available_tools() -> list[str]:
    """Every tool folder that carries a manifest.yml (same set explain_tool documents)."""
    if not TOOLS_ROOT.exists():
        return []
    return sorted(p.name for p in TOOLS_ROOT.iterdir() if (p / "manifest.yml").exists())


def _load_sections(tool: str) -> dict[str, Any]:
    """Raw dict of {section_name: parsed yml} for a tool's manifest-listed sections that exist."""
    man = TOOLS_ROOT / tool / "manifest.yml"
    manifest = yaml.safe_load(man.read_text())
    out: dict[str, Any] = {"_manifest": manifest}
    for ref in manifest.get("sections", []):
        p = TOOLS_ROOT / tool / ref["path"]
        if p.exists():
            out[ref["name"]] = yaml.safe_load(p.read_text())
    return out


def _formats(section: Any) -> list[str]:
    """The `format` field of each entry in an input/output section's `formats` list."""
    if not isinstance(section, dict):
        return []
    return [f["format"] for f in section.get("formats", []) if isinstance(f, dict) and f.get("format")]


def _category_tags(tool: str, meta: Any) -> list[str]:
    """meta.category_tags if present and non-empty, else the seed-table fallback (or [])."""
    if isinstance(meta, dict) and meta.get("category_tags"):
        return list(meta["category_tags"])
    seed = seed_category(tool)
    return [seed] if seed else []


def tool_record(tool: str) -> dict[str, Any]:
    """Build the flat catalog record for one tool. Never raises for a merely-incomplete workbook."""
    sec = _load_sections(tool)
    manifest = sec.get("_manifest", {})
    meta = sec.get("meta") or {}
    summary = (meta.get("summary") or "").strip() if isinstance(meta, dict) else ""
    if summary.startswith("HRR_"):                 # unreviewed placeholder — not a real summary
        summary = ""
    try:
        reviewed = cl.is_reviewed(cl.load_contract(tool))
    except Exception:                              # noqa: BLE001 - a broken contract shouldn't drop the tool
        reviewed = False
    return {
        "tool": tool,
        "version": manifest.get("version"),
        "summary": summary,
        "category_tags": _category_tags(tool, meta),
        "input_formats": _formats(sec.get("input")),
        "output_formats": _formats(sec.get("output")),
        "runtimes": manifest.get("runtimes", []),
        "reviewed": reviewed,
    }


_CACHE: Optional[list[dict[str, Any]]] = None


def catalog() -> list[dict[str, Any]]:
    """All tool records (cached for the process). Call invalidate() after a tool is added/edited."""
    global _CACHE
    if _CACHE is None:
        records = []
        for tool in available_tools():
            try:
                records.append(tool_record(tool))
            except Exception:                      # noqa: BLE001 - skip a broken tool, keep the rest
                continue
        _CACHE = records
    return _CACHE


def invalidate() -> None:
    """Drop the cached catalog (call after add_tool writes a new manifest/sections)."""
    global _CACHE
    _CACHE = None


def find(*, category: Optional[str] = None, input_format: Optional[str] = None,
         text: Optional[str] = None) -> list[dict[str, Any]]:
    """Filter the catalog. All given constraints must hold (AND). Deterministic + citable.

      category      — exact match against a record's category_tags
      input_format  — case-insensitive membership in input_formats (e.g. 'fastq')
      text          — case-insensitive substring over tool name + summary (keyword fallback)
    """
    out = catalog()
    if category:
        out = [r for r in out if category in r["category_tags"]]
    if input_format:
        fmt = input_format.lower()
        out = [r for r in out if any(fmt == f.lower() for f in r["input_formats"])]
    if text:
        t = text.lower()
        out = [r for r in out if t in (r["tool"] + " " + r["summary"]).lower()]
    return out
