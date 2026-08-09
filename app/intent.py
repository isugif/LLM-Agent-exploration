"""Intent classification — the chat front door.

This module only turns a message into a RAW typed Intent (the LLM proposes; offline it defaults to
`other`). All deterministic grounding — correcting a weak classification and filling slots (tool,
file) from the message + conversation memory — lives in `app/resolve.py`, which the router applies
right after `classify`. Keeping the two separate makes the LLM step swappable and the grounding
auditable.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

IntentName = Literal["describe_data", "explain_tool", "find_tool", "propose_strategy",
                     "run_pipeline", "add_tool", "other"]

_SYSTEM = (
    "You classify a scientist's bioinformatics request into one intent and extract only what is "
    "explicitly stated (use 'unknown' otherwise). Set `tool` to the program named, if any. Intents: "
    "describe_data (inspect/summarize a DATA FILE, e.g. a FASTQ), "
    "explain_tool (a question ABOUT a specific NAMED tool/program: what it does, how to run it, its "
    "parameters/options — set `tool`), "
    "find_tool (a cross-tool question with NO specific tool named: which/what tool does X, takes "
    "input Y, or is good for Z — e.g. 'which tool takes fastq', 'what's good for alignment'), "
    "propose_strategy (what analysis could I do), "
    "run_pipeline (actually run a tool on a file), "
    "add_tool (install/add a tool), other."
)


class Intent(BaseModel):
    """Typed classification of a chat message (before deterministic grounding)."""
    intent: IntentName = "other"
    files: list[str] = Field(default_factory=list, description="data file paths mentioned")
    assay: str = "unknown"
    organism: str = "unknown"
    goal: str = "unknown"
    tool: str = "unknown"
    confidence: float = 0.0


def classify(message: str, provider, history: Optional[list[dict]] = None) -> Intent:
    """Return a RAW Intent from the LLM (offline: `other`). `resolve.resolve()` grounds it afterward.
    Recent history is included so the model can resolve follow-ups ("what about the other one?")."""
    if getattr(provider, "name", "null") != "null":
        prompt = message
        if history:
            recent = "\n".join(f"{t.get('role', 'user')}: {(t.get('content') or '').strip()}"
                               for t in history[-6:] if (t.get('content') or '').strip())[-1200:]
            prompt = f"Recent conversation:\n{recent}\n\nNew message: {message}"
        parsed = provider.extract(Intent, system=_SYSTEM, prompt=prompt)
        if parsed is not None:
            return parsed
    return Intent()   # 'other' — the resolver grounds it deterministically


STUB_CAPABILITIES = {
    "propose_strategy": "propose an analysis strategy for your data",
}


def stub_text(intent: Intent) -> str:
    """Friendly 'not wired yet' message for intents beyond v1's capabilities."""
    want = STUB_CAPABILITIES.get(intent.intent, "handle that")
    return (f"I recognized that you'd like to **{want}** — that capability isn't wired up yet. "
            f"Right now I can profile a FASTQ, explain a documented tool, run a tool through the four "
            f"harnesses, and install/document a new tool. Try \"tell me about fastqc\".")
