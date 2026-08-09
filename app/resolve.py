"""Deterministic grounding / resolution layer for the chat router.

The LLM proposes an intent; this layer GROUNDS it — the same shape as the onboarding harness's
declared-vs-measured reconciliation, moved to the chat front door:

  1. correct a weak/ambiguous classification from strong deterministic signals (a documented tool
     named, a FASTQ path, an install/run keyword), and
  2. fill missing slots (tool, file) from the message, then from the conversation (memory).

It runs for EVERY intent, so all capabilities get weak-model compensation + memory for free, and it
keeps behaviour consistent across Ollama and Claude. Conservative by design: correct only on strong
signals and prefer asking (the router asks when a required slot stays unresolved). Every inference is
returned as a note so the UI can show what was grounded.

Operates on an intent duck-typed as having `.intent`, `.tool`, `.files` (avoids importing the model).
"""

from __future__ import annotations

import re
from typing import Optional

FASTQ_RE = re.compile(r"\S+\.(?:fastq|fq)(?:\.gz)?", re.IGNORECASE)
FLAG_RE = re.compile(r"(?:^|\s)--?[A-Za-z][\w-]*")
_RUN_RE = re.compile(r"\brun\b", re.IGNORECASE)
_ADD_RE = re.compile(r"\b(?:install|add(?:\s+the)?(?:\s+tool)?)\s+([A-Za-z0-9][\w.\-]+)", re.IGNORECASE)
# a tool-less "which/what/recommend … tool/program" discovery question -> find_tool (cross-tool RAG)
_FIND_RE = re.compile(
    r"\b(?:which|what|whats|recommend|suggest|best|any|is there a?)\b.{0,40}"
    r"\b(?:tool|tools|program|programs|software|package)\b", re.IGNORECASE)
# a first-person, past-tense recall question about THIS session's runs -> session_query
_SESSION_RE = re.compile(
    r"(?:\bdid i\b|\bhave i\b|\bi (?:ran|did|already)\b"
    r"|\bmy (?:run|runs|results?|output|outputs|session)\b"
    r"|\b(?:last|previous|earlier) run\b"
    r"|\bwhere\b.{0,40}\b(?:output|outputs|results?|wrote|saved|write)\b"
    r"|\bwhat (?:were|was|are)\b.{0,40}\b(?:results?|verdict|output|summary|metrics?)\b"
    r"|\bresults?\b.{0,20}\bagain\b)", re.IGNORECASE)

# Slots each intent needs before it can act. If unresolved after grounding, the router asks.
# (run_pipeline's tool defaults to fastqc, so only `file` is required.)
REQUIRED_SLOTS = {
    "describe_data": ["file"],
    "explain_tool": ["tool"],
    "run_pipeline": ["file"],
    "add_tool": ["tool"],
}
_WANTS_TOOL = {"explain_tool", "run_pipeline", "add_tool"}
_WANTS_FILE = {"describe_data", "run_pipeline"}


# --------------------------------------------------------------------------- #
# signal registry
# --------------------------------------------------------------------------- #

def documented_tools() -> list[str]:
    from app.capabilities.explain_tool import available_tools   # lazy: avoid import cycles
    return available_tools()


def tool_in(text: str) -> Optional[str]:
    low = (text or "").lower()
    return next((t for t in documented_tools() if re.search(rf"\b{re.escape(t)}\b", low)), None)


def fastq_in(text: str) -> Optional[str]:
    m = FASTQ_RE.findall(text or "")
    return m[0] if m else None


def flag_in(text: str) -> bool:
    return bool(FLAG_RE.search(text or ""))


def add_tool_name(text: str) -> Optional[str]:
    m = _ADD_RE.search(text or "")
    return m.group(1).lower() if m else None


def last_entity(history: Optional[list[dict]], kind: str) -> Optional[str]:
    """Most-recent tool/file mentioned in the conversation (memory)."""
    for turn in reversed(history or []):
        content = turn.get("content") or ""
        hit = tool_in(content) if kind == "tool" else fastq_in(content)
        if hit:
            return hit
    return None


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #

def find_tool_question(message: str) -> bool:
    return bool(_FIND_RE.search(message or ""))


def session_question(message: str) -> bool:
    return bool(_SESSION_RE.search(message or ""))


def resolve(intent, message: str, history: Optional[list[dict]]) -> list[str]:
    """Mutate `intent` in place: correct classification + fill slots. Returns human-readable notes."""
    notes: list[str] = []
    named = tool_in(message)
    fq = fastq_in(message)

    # 0a) session_query: a first-person recall question about past runs ("where did I write the
    #     fastqc output", "what were the results"). Checked BEFORE find_tool so "which tool did I
    #     run?" is recall, not discovery. Gated on no file (a file present means describe/run).
    if not fq and session_question(message) and \
            intent.intent in ("other", "explain_tool", "find_tool", "describe_data", "propose_strategy"):
        intent.intent = "session_query"
        notes.append("intent=session_query (recall about this session's runs)")

    # 0b) find_tool: a discovery question with no specific tool named and no file to act on. Corrects
    #    both a non-committal 'other' and a weak model that guessed 'explain_tool' without a tool.
    elif not named and not fq and find_tool_question(message) and \
            intent.intent in ("other", "explain_tool", "propose_strategy"):
        intent.intent = "find_tool"
        notes.append("intent=find_tool (cross-tool discovery, no tool named)")

    # 1) intent correction — only when the model was non-committal ("other")
    if intent.intent == "other":
        if fq and _RUN_RE.search(message):
            intent.intent = "run_pipeline"; notes.append("intent=run_pipeline (FASTQ + 'run')")
        elif fq:
            intent.intent = "describe_data"; notes.append("intent=describe_data (FASTQ present)")
        elif add_tool_name(message):
            intent.intent = "add_tool"; intent.tool = add_tool_name(message)
            notes.append(f"intent=add_tool tool={intent.tool}")
        elif named:
            intent.intent = "explain_tool"; intent.tool = named
            notes.append(f"intent=explain_tool tool={named} (documented tool named)")
        elif flag_in(message) and last_entity(history, "tool"):
            intent.intent = "explain_tool"; intent.tool = last_entity(history, "tool")
            notes.append(f"intent=explain_tool tool={intent.tool} (flag + memory)")

    # 2) slot filling for the (possibly corrected) intent
    if intent.intent in _WANTS_TOOL:
        if named and named != intent.tool:
            intent.tool = named; notes.append(f"tool={named}")
        elif not intent.tool or intent.tool == "unknown":
            lt = last_entity(history, "tool")
            if lt:
                intent.tool = lt; notes.append(f"tool={lt} (from history)")
    if intent.intent in _WANTS_FILE and not intent.files:
        f = fq or last_entity(history, "file")
        if f:
            intent.files = [f]; notes.append(f"file={f}" + ("" if fq else " (from history)"))
    return notes


def missing_slot(intent) -> Optional[str]:
    """First required slot still unresolved — for a uniform clarifying question."""
    for slot in REQUIRED_SLOTS.get(intent.intent, []):
        if slot == "tool" and (not intent.tool or intent.tool == "unknown"):
            return "tool"
        if slot == "file" and not intent.files:
            return "file"
    return None


def ask_text(slot: str) -> str:
    if slot == "tool":
        return "Which tool? e.g. \"tell me about fastqc\"."
    if slot == "file":
        return "Which FASTQ file? Give me a path (e.g. shared/data/SRR11140744_10k.fastq.gz)."
    return "Could you clarify that?"
