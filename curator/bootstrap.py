"""Gated front-end: provision the tool, then curate — but ONLY if the install verifies.

    provision(tool) -> if not installed: STOP (blocked_install) -> else source_from_help -> curate

This is what makes install a first-class first step: no `--help`, no curation, no proceeding, until
the tool is actually installed and `--version` confirms it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from shared.sections.scaffold import write_machine_skeletons
from curator.providers.base import Provider
from curator.references import sourcing
from curator.stages.provision import ENV, ensure_installed, InstallOutcome
from curator.stages.steps import Outcome, SectionTask
from curator.nooa_curator.orchestrator import curate_tool

REPO = Path(__file__).resolve().parents[1]


def bootstrap_and_curate(
    tool: str,
    sections: list[str],
    providers: dict[str, Provider],
    *,
    allow_install: bool = True,
    propose: Optional[str] = None,
) -> dict:
    """Provision `tool` then curate `sections`. Returns:
       {status: "blocked_install", install: InstallOutcome}                 (gate tripped)
       {status: "ok", install: InstallOutcome, outcomes: list[Outcome]}     (proceeded)
    """
    inst: InstallOutcome = ensure_installed(tool, allow_install=allow_install, propose=propose)
    if not inst.installed:
        return {"status": "blocked_install", "install": inst}          # <-- THE GATE

    src = sourcing.source_from_help(tool, env=ENV)                      # help via the curator env
    tasks = [SectionTask(tool, s, src, example=None,
                         ctx={"source_version": inst.version} if s == "install" else {})
             for s in sections]
    outcomes: list[Outcome] = curate_tool(tasks, providers)

    # Lay down the standardized MACHINE-section skeletons (meta/execution/preconditions/must_not_use/
    # failure_modes) marked HRR_ — the curator does NOT auto-fill the enforceable contract; a human
    # reviews it. The harness refuses to route the tool until the HRR_ markers are removed.
    scaffolded = write_machine_skeletons(REPO / "bio-tools" / tool)     # skips any already-reviewed file
    return {"status": "ok", "install": inst, "outcomes": outcomes, "hrr_scaffolded": scaffolded}
