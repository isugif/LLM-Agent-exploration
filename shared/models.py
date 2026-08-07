"""Shared data structures passed between the four harnesses.

These dataclasses are framework-agnostic: the LangGraph nodes and the NOOA agents
both produce and consume them, so the two tracks can be diffed against each other
on identical inputs. Nothing in here imports langgraph or nooa.

Vocabulary (from the design note):
  * DECLARED facts  -> what the scientist asserts (parsed from their question).
  * MEASURED facts  -> what we probe from the actual files (ground truth).
  * A disagreement between the two is a first-class silent-error signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# --- Onboarding harness output -------------------------------------------------

@dataclass
class Spec:
    """The reconciled problem statement everything downstream routes on."""

    question: str
    deliverable: str                       # what the user wants out (load-bearing for judgment)
    declared: dict[str, Any]               # facts asserted by the user
    measured: dict[str, Any]               # facts probed from the input files
    disagreements: list[str] = field(default_factory=list)  # declared-vs-measured conflicts

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Judgment harness output ---------------------------------------------------

@dataclass
class RouteDecision:
    """Emitted by the judgment (fit-critic) harness before any compute happens."""

    action: str                            # "run" | "refuse"
    rationale: str
    confidence: float                      # 0.0 - 1.0
    precondition_failures: list[str] = field(default_factory=list)
    boundary_hits: list[str] = field(default_factory=list)  # tripped must-not-use lines

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Execution layer output ----------------------------------------------------

@dataclass
class RunResult:
    """Structured result of a deterministic tool run, plus its audit record."""

    tool: str
    ok: bool                               # convenience: exit_code == 0 and not error
    exit_code: Optional[int]
    stdout: str
    stderr: str
    output_dir: Optional[str]
    audit: dict[str, Any]                  # cmd, versions, timing, paths — the audit trail
    error: Optional[str] = None            # set when the tool could not be launched at all

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Diagnosis / evaluation harness output ------------------------------------

@dataclass
class Verdict:
    """Result of the diagnosis (crash) or evaluation (implausible output) harness.

    status:
      ok            -> output is within expected ranges
      anomaly       -> a metric is outside expected range (soft failure)
      failure       -> the run crashed and was diagnosed (hard failure)
      cannot_assess -> the harness refuses to judge (right to refuse)
    """

    status: str
    findings: list[str] = field(default_factory=list)
    escalate: bool = False                 # send to human curation?
    proposed_fix: Optional[str] = None     # for diagnosed crashes
    explanation: Optional[str] = None      # LLM plain-language explanation of flagged metrics
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
