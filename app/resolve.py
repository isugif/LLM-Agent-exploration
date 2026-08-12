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
from typing import Literal, Optional

from pydantic import BaseModel, Field

# The typed intent the deterministic router grounds. Formerly produced by an LLM classifier
# (app/intent.py, retired): when a model is present the agent loop handles routing; with no model,
# `resolve()` grounds a bare Intent() from deterministic signals, so the chat still works offline.
IntentName = Literal["describe_data", "explain_tool", "find_tool", "session_query",
                     "propose_strategy", "run_pipeline", "add_tool",
                     "describe_workdir", "set_workdir", "other"]


class Intent(BaseModel):
    """Typed classification of a chat message, then grounded in place by `resolve()`."""
    intent: IntentName = "other"
    files: list[str] = Field(default_factory=list, description="data file paths mentioned")
    assay: str = "unknown"
    organism: str = "unknown"
    goal: str = "unknown"
    tool: str = "unknown"
    confidence: float = 0.0


FASTQ_RE = re.compile(r"\S+\.(?:fastq|fq)(?:\.gz)?", re.IGNORECASE)
# a reference FASTA path; the negative lookahead stops '.fa' from matching inside '.fastq'
FASTA_RE = re.compile(r"\S+\.(?:fasta|fna|fa)(?:\.gz)?(?![A-Za-z0-9])", re.IGNORECASE)
ALN_RE = re.compile(r"\S+\.(?:bam|sam|cram)(?![A-Za-z0-9])", re.IGNORECASE)          # an alignment
GTF_RE = re.compile(r"\S+\.(?:gtf|gff3|gff)(?:\.gz)?(?![A-Za-z0-9])", re.IGNORECASE)  # an annotation
FLAG_RE = re.compile(r"(?:^|\s)--?[A-Za-z][\w-]*")
_RUN_RE = re.compile(r"\brun\b", re.IGNORECASE)
# a "how do I run …" instructions question — asks ABOUT running, so it's explain_tool, not a run
_HOWTO_RUN_RE = re.compile(r"\bhow\s+(?:to|do\s+i|can\s+i|would\s+i|should\s+i|does\s+one)\b", re.IGNORECASE)
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
# a reference to a run's output/results — only routed to recall when the session has runs (see resolve)
_OUTPUT_RE = re.compile(r"\b(?:output|outputs|results?|report|reports|summary|verdict|metrics?)\b", re.IGNORECASE)
# a question ABOUT the session itself (id/age/size) — routed to recall regardless of run count
_SESSION_META_RE = re.compile(
    r"\b(?:what|which)\b.{0,20}\bsession\b|\bsession\s*id\b|\bsession\s*info\b"
    r"|\bhow many runs\b|\bwhat tools?\b.{0,20}\b(?:used|run|ran)\b", re.IGNORECASE)
# working-directory control. SET: "set my working dir to X", "my data is in X", "cd X", "work in X"
# (captures the folder). DESCRIBE: "what's in my folder", "list my files", "what's my workdir".
_SET_WD_RE = re.compile(
    r"(?:set\s+(?:my\s+)?(?:working\s+)?(?:dir(?:ectory)?|workdir|cwd|folder)\s+to"
    r"|(?:my\s+)?data\s+(?:is|are|lives?)\s+in"
    r"|use\s+(?:folder|directory|dir)"
    r"|\bcd)\s+(?P<path>\S.*?)\s*$", re.IGNORECASE)
_DESC_WD_RE = re.compile(
    r"what(?:'s|\s+is)?\s+in\s+(?:my|the|this)\s+(?:folder|dir(?:ectory)?|workdir|working\s+dir(?:ectory)?)"
    r"|list\s+(?:my|the)\s+(?:files?|data|folder)"
    r"|what\s+(?:data|files?)\s+(?:do\s+i\s+have|are\s+(?:there|here|available))"
    r"|what(?:'s|\s+is)?\s+my\s+(?:current\s+|working\s+)?(?:dir(?:ectory)?|workdir|cwd|folder)"
    r"|show\s+(?:me\s+)?(?:my|the)\s+(?:folder|files?|working\s+dir(?:ectory)?)", re.IGNORECASE)

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


def fasta_ref_in(text: str) -> Optional[str]:
    """A reference-genome FASTA path mentioned in the message (for aligners)."""
    m = FASTA_RE.findall(text or "")
    return m[0] if m else None


def aln_in(text: str) -> Optional[str]:
    """A BAM/SAM/CRAM alignment path mentioned in the message (for rustqc / samtools tools)."""
    m = ALN_RE.findall(text or "")
    return m[0] if m else None


def gtf_in(text: str) -> Optional[str]:
    """A GTF/GFF annotation path mentioned in the message (for rustqc)."""
    m = GTF_RE.findall(text or "")
    return m[0] if m else None


# a path-like token: absolute/home/relative, or any word containing a slash (e.g. a directory to
# aggregate). Used for aggregator tools whose input is a DIRECTORY, not a typed filename.
PATH_RE = re.compile(r"(?:~|\.{1,2})?/[^\s]+|[A-Za-z0-9._-]+/[^\s]*")


def path_in(text: str) -> Optional[str]:
    """The first path-like token in the message (for a directory argument). Trailing punctuation
    trimmed. `None` if the message names no path."""
    m = PATH_RE.search(text or "")
    return m.group(0).rstrip(".,;)") if m else None


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


def output_question(message: str) -> bool:
    """Mentions a run's output/results — routed to recall only when the session actually has runs."""
    return bool(_OUTPUT_RE.search(message or ""))


def session_meta_question(message: str) -> bool:
    """Asks about the session itself (id/age/size/tools) — answerable even with zero runs."""
    return bool(_SESSION_META_RE.search(message or ""))


def workdir_path(message: str) -> Optional[str]:
    """The folder path from a 'set working directory' message, if any."""
    m = _SET_WD_RE.search(message or "")
    if not m:
        return None
    return (m.group("path") or "").strip().strip("\"'`").rstrip(".,")


def set_workdir_question(message: str) -> bool:
    return workdir_path(message) is not None


def describe_workdir_question(message: str) -> bool:
    return bool(_DESC_WD_RE.search(message or ""))


_SESSION_INTENTS = ("other", "explain_tool", "find_tool", "describe_data", "propose_strategy")


def resolve(intent, message: str, history: Optional[list[dict]],
            session: Optional[dict] = None) -> list[str]:
    """Mutate `intent` in place: correct classification + fill slots. Returns human-readable notes.

    `session` (optional) is a small context dict {"has_runs": bool, "tools": [...]} the router builds
    from the on-disk run-log; it lets a question about "the fastqc output" resolve to recall instead
    of demanding a file.
    """
    notes: list[str] = []

    # 0) working-directory control — set/inspect the folder the app resolves data paths against.
    #    Checked first (strong, explicit phrasing) and short-circuits the rest of resolution.
    if set_workdir_question(message):
        intent.intent = "set_workdir"; notes.append("intent=set_workdir")
        return notes
    if describe_workdir_question(message):
        intent.intent = "describe_workdir"; notes.append("intent=describe_workdir")
        return notes

    named = tool_in(message)
    fq = fastq_in(message)
    has_runs = bool(session and session.get("has_runs"))

    # 0a) session_query: a recall question about past runs. Either explicit first-person phrasing
    #     ("where did I write the fastqc output", "what were the results"), OR — when this session has
    #     runs — a reference to a run's output/results ("what can you tell me about the fastqc
    #     output?"). Checked BEFORE find_tool so "which tool did I run?" is recall, not discovery.
    #     Gated on no file (a file present means describe/run).
    if not fq and intent.intent in _SESSION_INTENTS and \
            (session_question(message) or session_meta_question(message)
             or (has_runs and output_question(message))):
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
        elif _RUN_RE.search(message) and named and not _HOWTO_RUN_RE.search(message):
            # "run multiqc", "run rustqc on x.bam" — an explicit run verb + a documented tool. No
            # file is needed to route: an aggregator defaults to the session dir; a file-input tool
            # gets a 'which file?' from the missing-slot check. ("how do I run X" stays explain.)
            intent.intent = "run_pipeline"; intent.tool = named
            notes.append(f"intent=run_pipeline tool={named} ('run' + documented tool)")
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
        # the run input may be a FASTQ or an alignment (BAM/SAM/CRAM, for rustqc/samtools tools)
        f = fq or (aln_in(message) if intent.intent == "run_pipeline" else None) \
            or last_entity(history, "file")
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


STUB_CAPABILITIES = {
    "propose_strategy": "propose an analysis strategy for your data",
}


def stub_text(intent) -> str:
    """Friendly 'not wired yet' message for intents beyond the deterministic router's capabilities."""
    want = STUB_CAPABILITIES.get(intent.intent, "handle that")
    return (f"I recognized that you'd like to **{want}** — that capability isn't wired up in the "
            f"deterministic fallback. Connect a model (Claude/Ollama) for the full agent, or try "
            f"\"tell me about fastqc\" / \"profile <file>.fastq.gz\".")
