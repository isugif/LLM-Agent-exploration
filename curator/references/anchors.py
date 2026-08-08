"""Type-aware reference anchors — our clean-model equivalent of the skill's demos.md `Demo map`.

The skill anchors on a *type-matched* demo tool (fastqc=T1, samtools=T2, hisat2/star=T5, multiqc=T4)
rather than a single fixed example. We do the same: given the section + the target tool's type, pick a
clean section from the representative tool for that type to use as the few-shot anchor.

Binding constraint carried over from demos.md (DB3): the anchor is for STRUCTURE/STYLE only —
`SOURCE > PATTERN > DEMO`. The transfer stage still extracts facts from the source, never the anchor;
validation still catches fabrication. So a fallback anchor (when a type has no representative yet) is
safe: it shapes output, it does not supply facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from shared.sections.schemas import schema_for

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "bio-tools"

# ideal representative tool per type (the "Demo map"). Not all exist yet in bio-tools/; anchor_for
# falls back gracefully. Add a tool's clean/ folder to make it a real anchor for its type.
REPRESENTATIVE = {
    "single_command": "fastqc",
    "aggregator": "multiqc",
    "multi_step": "hisat2",        # add bio-tools/hisat2/clean to activate; else falls back
    "subcommand_toolkit": "samtools",
    "helper": "samtools",
}
FALLBACK = "fastqc"


def _load(tool: str, section: str) -> Optional[BaseModel]:
    path = TOOLS / tool / "clean" / f"{section}.yml"
    if not path.exists():
        return None
    return schema_for(section).model_validate(yaml.safe_load(path.read_text()))


def anchor_for(section: str, tool_type: str) -> Optional[BaseModel]:
    """Return a type-matched clean section to use as the few-shot anchor, or None if unavailable.

    Tries the type's representative tool first, then the global fallback (fastqc). Returns None only
    if neither has that section — in which case transfer runs example-free (schema still guides it).
    """
    for tool in (REPRESENTATIVE.get(tool_type, FALLBACK), FALLBACK):
        obj = _load(tool, section)
        if obj is not None:
            return obj
    return None


def anchor_source(section: str, tool_type: str) -> Optional[str]:
    """Which tool actually supplied the anchor (for logging/traceability)."""
    for tool in (REPRESENTATIVE.get(tool_type, FALLBACK), FALLBACK):
        if (TOOLS / tool / "clean" / f"{section}.yml").exists():
            return tool
    return None
