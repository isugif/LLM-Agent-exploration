"""Gated front-end: provision the tool, then curate — but ONLY if the install verifies.

    provision(tool) -> if not installed: STOP (blocked_install) -> else source_from_help -> curate

This is what makes install a first-class first step: no `--help`, no curation, no proceeding, until
the tool is actually installed and `--version` confirms it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from shared.sections.scaffold import write_machine_skeletons, machine_manifest_entries
from shared.sections.schemas import Manifest
from curator.providers.base import Provider
from curator.references import sourcing
from curator.stages.provision import ENV, ensure_installed, InstallOutcome
from curator.stages.steps import Outcome, SectionTask
from curator.nooa_curator.orchestrator import curate_tool

REPO = Path(__file__).resolve().parents[1]

# per context section: (one-line purpose, when the harness should open it) — mirrors the fastqc manifest
_CTX_META: dict[str, tuple[str, str]] = {
    "install":      ("how to install and verify the tool",       "install_error"),
    "input":        ("accepted formats, compression, layouts",   "always"),
    "output":       ("output artifacts and key files",           "always"),
    "usage":        ("representative invocations",                "always"),
    "options":      ("common flags and their meaning",           "always"),
    "dependencies": ("required + optional dependencies",         "install_error"),
    "source":       ("homepage / repository / docs links",       "citation_request"),
    "citations":    ("primary publication, license, related",    "citation_request"),
}


def _persist_sections(tool_dir: Path, outcomes: list[Outcome]) -> list[str]:
    """Write each VALID curated context section to <tool_dir>/clean/<section>.yml. Unresolved sections
    are skipped (their facts didn't validate, so we don't commit them). Returns the paths written."""
    clean = tool_dir / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    written = []
    for o in outcomes:
        if o.status != "valid" or o.section not in _CTX_META:
            continue
        path = clean / f"{o.section}.yml"
        body = yaml.safe_dump(o.obj, sort_keys=False, default_flow_style=False, allow_unicode=True)
        path.write_text("# CLEAN context section (curator-generated). Validates against schemas.py.\n" + body)
        written.append(str(path))
    return written


def _write_manifest(tool_dir: Path, tool: str, version: Optional[str]) -> str:
    """Build/refresh <tool_dir>/manifest.yml: machine skeleton refs + a context ref for every clean
    context yml present on disk (idempotent — re-runs pick up previously-curated sections). Validated
    against the Manifest schema before writing."""
    clean = tool_dir / "clean"
    ctx = [{"name": name, "purpose": purpose, "load_when": load_when,
            "machine": False, "path": f"clean/{name}.yml"}
           for name, (purpose, load_when) in _CTX_META.items() if (clean / f"{name}.yml").exists()]
    manifest = {"tool": tool, "version": str(version or "unknown"),
                "runtimes": [], "sections": machine_manifest_entries() + ctx}
    Manifest.model_validate(manifest)                                  # fail loud on a bad manifest
    path = tool_dir / "manifest.yml"
    path.write_text("# Per-tool index (curator-generated). Validates against schemas.py:Manifest.\n"
                    + yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False, allow_unicode=True))
    return str(path)


def bootstrap_and_curate(
    tool: str,
    sections: list[str],
    providers: dict[str, Provider],
    *,
    binary: Optional[str] = None,
    allow_install: bool = True,
    propose: Optional[str] = None,
    url: Optional[str] = None,
) -> dict:
    """Provision `tool` then curate `sections`. Returns:
       {status: "blocked_install", install: InstallOutcome}                 (gate tripped)
       {status: "ok", install: InstallOutcome, outcomes: list[Outcome]}     (proceeded)

    `tool` is the bioconda package / workbook id (lowercase); `binary` overrides the auto-resolved
    executable when it differs (e.g. package `star` -> binary `STAR`). `url` adds a doc/README source
    (appended to `--help`) for tools whose help is truncated or missing.
    """
    inst: InstallOutcome = ensure_installed(tool, binary=binary, allow_install=allow_install,
                                            propose=propose)
    if not inst.installed:
        return {"status": "blocked_install", "install": inst}          # <-- THE GATE

    src = sourcing.source_from_help(inst.binary or tool, env=ENV)       # help via the curator env
    if url:
        src = (src + "\n\n" + sourcing.source_from_url(url)).strip()    # extra doc source (README/docs)
    tasks = [SectionTask(tool, s, src, example=None,
                         ctx={"source_version": inst.version} if s == "install" else {})
             for s in sections]
    outcomes: list[Outcome] = curate_tool(tasks, providers)

    tool_dir = REPO / "bio-tools" / tool
    # Persist the VALID curated context (fact) sections as the tool's clean workbook ymls.
    sections_written = _persist_sections(tool_dir, outcomes)

    # Lay down the standardized MACHINE-section skeletons (meta/execution/preconditions/must_not_use/
    # failure_modes) marked HRR_ — the curator does NOT auto-fill the enforceable contract; a human
    # reviews it. The harness refuses to route the tool until the HRR_ markers are removed.
    scaffolded = write_machine_skeletons(tool_dir)                      # skips any already-reviewed file

    # Index everything on disk so the harness can load the tool.
    manifest_path = _write_manifest(tool_dir, tool, inst.version)

    return {"status": "ok", "install": inst, "outcomes": outcomes,
            "sections_written": sections_written, "hrr_scaffolded": scaffolded,
            "manifest": manifest_path}
