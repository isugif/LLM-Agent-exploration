"""Framework-agnostic pipeline stages for the curator.

All stage logic lives here as pure functions; the LangGraph graph and the NOOA orchestrator only
WIRE these (nodes/edges vs. plain if/while). This is the same shared-core pattern as the harness —
it keeps the two orchestrations honest (same behavior) and cheap (no duplicated logic).

Pipeline (clean-source curation):
    classify → transfer → enrich → validate → (fix → validate)* → finalize

Note vs the original skill: its S3 (tokens) and S4 (cross-links) stages are Jekyll RENDER concerns —
the clean fact-only source has no [[TOKEN]]/embeds — so they move to the M3.4 render step, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

from shared.sections.schemas import schema_for
from curator.providers.base import LLMError, Provider
from curator.providers.structured import fill
from curator.validators.framework import CheckResult, run_checks
from curator.references.tool_types import classify as _classify_type
from curator.references.anchors import anchor_for
from curator.references.generalize import generalize

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "bio-tools"


# --------------------------------------------------------------------------- #
# task + outcome
# --------------------------------------------------------------------------- #

@dataclass
class SectionTask:
    """One unit of curation: turn `source_text` into a clean object for `section`."""
    tool_id: str
    section: str
    source_text: str
    example: Optional[BaseModel]      # a filled reference instance (few-shot anchor)
    ctx: dict[str, Any] = field(default_factory=dict)   # validator context (e.g. source_version)


@dataclass
class Outcome:
    section: str
    status: str                       # "valid" | "unresolved"
    attempts: int
    obj: Optional[dict]               # the final object as a plain dict (None if never produced)
    results: list[CheckResult] = field(default_factory=list)
    tool_type: Optional[str] = None


def build_tasks(tool_id: str, sections: list[str]) -> list[SectionTask]:
    """Bootstrap tasks from a tool's EXISTING prose ymls (the migration source).

    The prose yml carries the facts (in its note/warning/variants prose); source-transfer extracts
    them into the clean schema. The committed clean/<section>.yml is used as the few-shot example.
    """
    manifest = yaml.safe_load((TOOLS / tool_id / "manifest.yml").read_text())
    version = manifest.get("version")
    tasks: list[SectionTask] = []
    for section in sections:
        prose = TOOLS / tool_id / f"{section}.yml"
        example_path = TOOLS / tool_id / "clean" / f"{section}.yml"
        example = None
        if example_path.exists():
            example = schema_for(section).model_validate(yaml.safe_load(example_path.read_text()))
        ctx = {"source_version": version} if section == "install" else {}
        tasks.append(SectionTask(tool_id, section, prose.read_text(), example, ctx))
    return tasks


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #

def classify(source_text: str, provider: Provider | None = None) -> str:
    """R0 — classify the tool's shape (single_command | subcommand_toolkit | helper | aggregator |
    multi_step). Delegates to the reference taxonomy (references/tool_types.py), which ports the
    skill's patterns.md T1-T5 + R0A precedence."""
    return _classify_type(source_text)


def transfer(task: SectionTask, provider: Provider) -> BaseModel:
    """S1 — source-transfer: fill the section's typed schema from the source, no fabrication.

    Anchor selection: an explicit `task.example` (e.g. a tool's own prior clean section, during
    migration) wins. Otherwise — the novel-tool path — we pick a TYPE-MATCHED anchor from the
    reference set (references/anchors.py), classifying the tool from its source first. The anchor
    shapes structure/style only; facts still come solely from the source.
    """
    example = task.example
    if example is None:
        example = anchor_for(task.section, classify(task.source_text))
    if example is not None:
        # DB3 prevention: mask tool-specific facts in the anchor for leak-prone sections so the model
        # can't copy them; facts must come from SOURCE. No-op for low-leak sections.
        example = generalize(task.section, example)
    return fill(
        provider, schema_for(task.section),
        instruction=(f"Extract the '{task.section}' facts for this tool from the SOURCE. "
                     "Use only what the source states; strip any markdown code fences from commands."),
        source=task.source_text,
        example=example,
    )


def enrich(task: SectionTask, obj: BaseModel, provider: Provider) -> BaseModel:
    """S5 — enrichment: add a source-backed note if the section supports one and lacks it.

    Best-effort: enrichment never fails the pipeline (on any LLM error we keep the object as-is).
    Only touches a `notes`/`note` field; never invents facts.
    """
    if not hasattr(obj, "notes"):
        return obj
    if getattr(obj, "notes"):
        return obj                    # already has notes; don't pad
    try:
        from pydantic import BaseModel as _BM

        class _Note(_BM):
            note: str
        out = fill(
            provider, _Note,
            instruction="Give ONE short, factual, source-backed caveat a user should know for this "
                        "section. If the source offers none, return an empty string.",
            source=task.source_text,
        )
        if out.note.strip():
            obj = obj.model_copy(update={"notes": [out.note.strip()]})
    except LLMError:
        pass
    return obj


def validate(task: SectionTask, obj: BaseModel) -> list[CheckResult]:
    """V — run the schema gate + section checks against the object's data.

    The source text is threaded into the check context so source-parity checks (e.g. flag grounding)
    can verify every generated flag exists in the tool's --help — catching anchor leaks (DB3).
    """
    ctx = {**task.ctx, "source_text": task.source_text}
    return run_checks(task.section, obj.model_dump(by_alias=True), ctx)


def fix(task: SectionTask, obj: BaseModel, failures: list[CheckResult], provider: Provider) -> BaseModel:
    """Targeted repair: re-fill the schema, told exactly which checks failed and why.

    This is the fix in the validate→fix→revalidate CYCLE — the step the text skill could not reliably
    self-run. It stays deterministic in shape (typed fill) and only reacts to concrete failure codes.
    """
    problems = "\n".join(f"- {f.check_id} [{f.code}]: {f.detail}" for f in failures)
    src_version = task.ctx.get("source_version")
    hint = f"\nThe authoritative version is {src_version!r}." if src_version else ""
    return fill(
        provider, schema_for(task.section),
        instruction=(f"Revise the '{task.section}' object to FIX these validation failures:\n{problems}"
                     f"{hint}\nReturn the corrected object; keep all other facts from the SOURCE."),
        source=task.source_text,
        example=obj,                  # the current (broken) object anchors the corrected shape
    )


def finalize(results: list[CheckResult]) -> bool:
    """Boolean gate: the section is done only if every check passed."""
    return all(r.ok for r in results)
