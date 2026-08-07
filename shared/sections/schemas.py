"""LLM-readable section schemas — the single source of truth for a tool's facts.

These pydantic models define the CLEAN, fact-only representation of each documentation section.
They deliberately contain NO Jekyll render mechanics ([[TOKEN]], {{VAR}}, embeds, fenced code,
index-mapping) — those are a rendering concern re-applied later by the workbook render step. Keeping
the source fact-only is what makes it reliable for a model to read AND write.

The schema is the first validation gate: the curator fills these slots via structured extraction and
the object is validated on return, so structure can't drift.

Two families of section:
  * MACHINE  — harness-checkable (execution, preconditions, ...). Assembled into the runtime contract.
  * CONTEXT  — human/prose facts (install, input, citations, ...). Loaded situationally.

This milestone (M3.1) ships three CONTEXT sections: install, input, citations.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #

class InstallMethod(BaseModel):
    """One installation route. `command` is a plain shell string — no code fences."""
    manager: Literal["conda", "mamba", "micromamba", "pip", "source", "brew", "docker", "other"]
    command: str = Field(description="the exact install command, plain text, no ``` fences")


class InstallSection(BaseModel):
    version: str = Field(description="the tool version these instructions install/pin")
    methods: list[InstallMethod] = Field(description="one entry per supported install route")
    verify_command: str = Field(description="command that confirms the install, e.g. 'fastqc --version'")
    verify_expected: Optional[str] = Field(
        default=None, description="expected substring of the verify output, e.g. 'FastQC v0.12.1'")
    notes: list[str] = Field(default_factory=list, description="short factual install caveats")


# --------------------------------------------------------------------------- #
# input
# --------------------------------------------------------------------------- #

class InputFormat(BaseModel):
    format: str = Field(description="accepted input format or biodata type, e.g. 'fastq'")
    compression: list[str] = Field(default_factory=list, description="e.g. ['gzip', 'none']")
    layouts: list[str] = Field(default_factory=list, description="e.g. ['SE', 'PE'] when applicable")
    note: Optional[str] = None


class InputSection(BaseModel):
    formats: list[InputFormat] = Field(description="accepted inputs, in dependency order")
    note: Optional[str] = Field(default=None, description="one factual note on provenance/readiness")


# --------------------------------------------------------------------------- #
# citations
# --------------------------------------------------------------------------- #

class RelatedPublication(BaseModel):
    title: str
    link: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class CitationsSection(BaseModel):
    primary_text: str = Field(description="the full primary publication citation, plain text")
    doi: Optional[str] = None
    url: Optional[str] = None
    license: Optional[str] = Field(default=None, description="SPDX id or license name, e.g. 'GPL-3.0'")
    related: list[RelatedPublication] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# MACHINE sections — assembled into the runtime contract the harness consumes
# --------------------------------------------------------------------------- #

class MetaSection(BaseModel):
    """Tool-level machine facts not owned by another section."""
    summary: str = Field(description="one-paragraph what-it-does, used by the judgment prompt")
    expectations_ref: Optional[str] = Field(
        default=None, description="filename of the shared assay expectation table, e.g. rnaseq_qc.yaml")


class ExecutionSection(BaseModel):
    """How the generic runner invokes the tool. `argv` is a token list (no shell)."""
    argv: list[str] = Field(description="token list with {input}/{out_dir}/{threads} placeholders")
    version_argv: Optional[list[str]] = None
    install_hint: Optional[str] = None


class Precondition(BaseModel):
    id: str
    # `assert` is a Python keyword; store as assert_ but read/write the yaml key "assert".
    assert_: str = Field(alias="assert", description="restricted bool expr over measured.*/declared.*")
    severity: Literal["block", "warn"]
    message: Optional[str] = None
    model_config = {"populate_by_name": True}


class Boundary(BaseModel):
    id: str
    boundary: str = Field(description="prose statement of an off-label use")
    keywords: list[str] = Field(default_factory=list, description="deliverable keywords that trip it")


class FailureMode(BaseModel):
    id: str
    signal: str = Field(description="stderr/stdout substring the diagnosis harness greps for")
    fix: str


# list-valued machine sections are validated item-by-item (see validators / contracts_lib)
LIST_SECTION_ITEM = {
    "preconditions": Precondition,
    "must_not_use": Boundary,
    "failure_modes": FailureMode,
}

# machine section name -> which key it contributes to the assembled contract dict
MACHINE_SECTIONS = {"meta", "execution", "preconditions", "must_not_use", "failure_modes"}


# --------------------------------------------------------------------------- #
# manifest — the situational-loading index
# --------------------------------------------------------------------------- #

# When the harness should bother opening a section (keeps token cost down: load the manifest, then
# open only the section a situation calls for).
LoadWhen = Literal["always", "install_error", "citation_request", "on_crash", "results_eval"]


class SectionRef(BaseModel):
    name: str
    purpose: str = Field(description="one line: what facts this section holds")
    load_when: LoadWhen
    machine: bool = Field(description="True if harness-checkable (assembled into the contract)")
    path: str = Field(description="relative path to the section yml, from the tool folder")


class Manifest(BaseModel):
    tool: str
    version: str
    sections: list[SectionRef]


# --------------------------------------------------------------------------- #
# registry — name -> schema (the curator and validators look sections up here)
# --------------------------------------------------------------------------- #

SECTION_SCHEMAS: dict[str, type[BaseModel]] = {
    # context sections
    "install": InstallSection,
    "input": InputSection,
    "citations": CitationsSection,
    # machine sections (meta/execution are objects; the list sections validate item-by-item)
    "meta": MetaSection,
    "execution": ExecutionSection,
}


def schema_for(section: str) -> type[BaseModel]:
    if section not in SECTION_SCHEMAS:
        raise KeyError(f"no schema for section '{section}'. Known: {sorted(SECTION_SCHEMAS)}")
    return SECTION_SCHEMAS[section]
