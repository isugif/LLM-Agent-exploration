"""Intent router — the chat front door.

The LLM does ONE bounded structured classification (robust to phrasing); deterministic code
dispatches. Same seam as onboarding_node's provider.extract(DeclaredFacts, ...), moved to the front.

v1 wires only `describe_data`; every other intent is classified but returns a graceful stub so the
UI shows what's coming without pretending to do it.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

IntentName = Literal["describe_data", "explain_tool", "propose_strategy", "run_pipeline",
                     "add_tool", "other"]

# A FASTQ path mentioned in free text (non-capturing group so findall returns the whole match).
FASTQ_RE = re.compile(r"\S+\.(?:fastq|fq)(?:\.gz)?", re.IGNORECASE)

_SYSTEM = (
    "You classify a scientist's bioinformatics request into one intent and extract only what is "
    "explicitly stated (use 'unknown' otherwise). Set `tool` to the program named, if any. Intents: "
    "describe_data (inspect/summarize a DATA FILE, e.g. a FASTQ), "
    "explain_tool (a question ABOUT a tool/program itself: what it does, how to run it, its "
    "parameters/options — set `tool`), "
    "propose_strategy (what analysis could I do), "
    "run_pipeline (actually run a tool on a file), "
    "add_tool (install/add a tool), other."
)


class Intent(BaseModel):
    """Typed classification of a chat message."""
    intent: IntentName = "other"
    files: list[str] = Field(default_factory=list, description="data file paths mentioned")
    assay: str = "unknown"
    organism: str = "unknown"
    goal: str = "unknown"
    tool: str = "unknown"
    confidence: float = 0.0


_KNOWN_TOOLS = ("fastqc", "multiqc", "hisat2", "star")


_ADD_RE = re.compile(r"\b(?:install|add(?:\s+the)?(?:\s+tool)?)\s+([A-Za-z0-9][\w.\-]+)", re.IGNORECASE)


def _documented_tools() -> list[str]:
    """Tools that have a curated workbook (for offline explain_tool detection)."""
    from app.capabilities.explain_tool import available_tools
    return available_tools()


def _heuristic(message: str) -> Intent:
    """LLM-off fallback: 'run' + FASTQ => run_pipeline; 'install X' => add_tool; a documented tool
    name (no file) => explain_tool; a FASTQ alone => describe_data; else other."""
    files = FASTQ_RE.findall(message)
    low = message.lower()
    if files and re.search(r"\brun\b", low):
        tool = next((t for t in _KNOWN_TOOLS if t in low), "fastqc")
        return Intent(intent="run_pipeline", files=files, tool=tool, confidence=0.3)
    m = _ADD_RE.search(message)
    if m and not files:
        return Intent(intent="add_tool", tool=m.group(1).lower(), confidence=0.3)
    if not files:
        named = next((t for t in _documented_tools() if re.search(rf"\b{re.escape(t)}\b", low)), None)
        if named:
            return Intent(intent="explain_tool", tool=named, confidence=0.3)
    return Intent(intent="describe_data" if files else "other", files=files, confidence=0.3)


def classify(message: str, provider, history: Optional[list[dict]] = None) -> Intent:
    """Classify a message into an Intent. Recent history lets the LLM resolve follow-ups ("what about
    the other one?"). Falls back to a heuristic when the LLM is unavailable."""
    parsed = None
    if getattr(provider, "name", "null") != "null":
        prompt = message
        if history:
            recent = "\n".join(f"{t.get('role', 'user')}: {(t.get('content') or '').strip()}"
                               for t in history[-6:] if (t.get('content') or '').strip())[-1200:]
            prompt = f"Recent conversation:\n{recent}\n\nNew message: {message}"
        parsed = provider.extract(Intent, system=_SYSTEM, prompt=prompt)
    if parsed is None:
        return _heuristic(message)
    if not parsed.files:                       # backstop: catch a path the model overlooked
        parsed.files = FASTQ_RE.findall(message)
    return parsed


STUB_CAPABILITIES = {
    "propose_strategy": "propose an analysis strategy for your data",
}


def stub_text(intent: Intent) -> str:
    """Friendly 'not wired yet' message for intents beyond v1's describe_data."""
    want = STUB_CAPABILITIES.get(intent.intent, "handle that")
    return (f"I recognized that you'd like to **{want}** — that capability isn't wired up yet. "
            f"Right now I can **profile a sequencing data file**: point me at a FASTQ "
            f"(e.g. `shared/data/SRR11140744_10k.fastq.gz`) and ask what I can tell you about it.")
