"""add_tool — install + document a tool via the curator, streaming each stage.

Mirrors curator.bootstrap.bootstrap_and_curate but yields between steps so the chat shows a live
timeline: provision (install into the isolated curator-tools env) -> docs check -> source (--help)
-> curate the MISSING fact sections -> persist workbook -> scaffold the machine-section HRR
skeletons -> END at the human-review gate. Installing via chat yields a DOCUMENTED but UN-RUNNABLE
tool: the run_pipeline judgment harness refuses to route it until a human replaces the HRR_ markers.

Idempotent by design: a re-run checks which section docs already exist and curates only the missing
ones — so an interrupted run recovers by re-running (no partial-persist bookkeeping needed).

Provisioning stays hardened by the curator (whitelisted bioconda/managers, shell=False, sanitized
names, no model-authored commands); the model only fills typed schemas from the tool's own --help.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from curator.providers import registry
from curator.bootstrap import _persist_sections, _write_manifest, REPO
from curator.references import sourcing
from curator.stages.provision import ENV, ensure_installed
from curator.stages.steps import SectionTask
from curator.nooa_curator.orchestrator import curate_section
from shared.sections.scaffold import write_machine_skeletons
from shared import catalog, contracts_lib as cl

_ROLES = ("transfer", "enrich", "fix")
_PROVIDER_MAP = {"claude": "claude-cli", "ollama": "ollama"}   # UI name -> curator registry name
DEFAULT_SECTIONS = ["usage", "options"]
TOOLS = REPO / "bio-tools"


def _providers(ui_provider: Optional[str]):
    override = _PROVIDER_MAP.get(ui_provider or "")            # None -> registry auto
    return {r: registry.resolve(r, override=override) for r in _ROLES}


def _missing(tool: str, sections: list[str]) -> list[str]:
    """Which requested section docs are NOT yet on disk for this tool."""
    clean = TOOLS / tool / "clean"
    return [s for s in sections if not (clean / f"{s}.yml").exists()]


def plan_for(tool: str, sections: Optional[list[str]] = None) -> list[str]:
    """Expected stage keys for the UI progress bar — reflects only the work actually needed."""
    sections = sections or DEFAULT_SECTIONS
    miss = _missing(tool, sections)
    steps = ["provision", "docs_check"]
    if miss:
        steps.append("source")
        steps += [f"curate:{s}" for s in miss]
    return steps + ["persist", "scaffold", "hrr_gate"]


def stage_events(tool: str, ui_provider: str = "auto", sections: Optional[list[str]] = None,
                 binary: Optional[str] = None, url: Optional[str] = None) -> Iterator[tuple[str, dict]]:
    """Blocking generator: yield (stage, payload) as the curator provisions + documents `tool`."""
    sections = sections or DEFAULT_SECTIONS
    tool_dir = TOOLS / tool

    inst = ensure_installed(tool, binary=binary)
    if not inst.installed:
        yield "provision", {"tool": tool, "installed": False, "reason": inst.reason}
        return
    yield "provision", {"tool": tool, "installed": True, "version": inst.version,
                        "binary": inst.binary, "method": inst.method}

    # Which docs already exist? Only curate the missing ones (idempotent re-run / recovery).
    missing = _missing(tool, sections)
    have = [s for s in sections if s not in missing]
    yield "docs_check", {"have": have, "missing": missing,
                         "manifest": (tool_dir / "manifest.yml").exists()}

    outcomes = []
    if missing:
        src = sourcing.source_from_help(inst.binary or tool, env=ENV)
        if url:
            src = (src + "\n\n" + sourcing.source_from_url(url)).strip()
        yield "source", {"chars": len(src), "url": url}

        providers = _providers(ui_provider)
        for s in missing:
            ctx = {"source_version": inst.version} if s == "install" else {}
            o = curate_section(SectionTask(tool, s, src, example=None, ctx=ctx), providers)
            outcomes.append(o)
            items = len((o.obj or {}).get("options") or (o.obj or {}).get("examples") or [])
            yield "curate", {"section": s, "status": o.status, "fixes": o.attempts, "items": items}

    written = _persist_sections(tool_dir, outcomes) if outcomes else []
    scaffolded = write_machine_skeletons(tool_dir)             # idempotent — skips existing
    manifest = _write_manifest(tool_dir, tool, inst.version)   # written once all files exist
    catalog.invalidate()                                       # new tool -> refresh find_tool's view
    yield "persist", {"sections_written": [Path(p).name for p in written],
                      "manifest": Path(manifest).name, "already_documented": not missing}
    yield "scaffold", {"hrr_files": [Path(p).name for p in scaffolded]}

    try:
        contract = cl.load_contract(tool)
        markers, reviewed = cl.find_hrr_markers(contract), cl.is_reviewed(contract)
    except Exception:                          # noqa: BLE001
        markers, reviewed = [], False
    yield "hrr_gate", {"tool": tool, "markers": len(markers), "reviewed": reviewed}


def to_event(stage: str, payload: dict) -> dict:
    """Attach a UI title (payload is already compact)."""
    titles = {
        "provision": "Provision (install)",
        "docs_check": "Check documents",
        "source": "Source (--help / docs)",
        "persist": "Persist workbook",
        "scaffold": "Scaffold machine sections",
        "hrr_gate": "Human-review gate",
    }
    title = f"Curate: {payload.get('section')}" if stage == "curate" else titles.get(stage, stage)
    return {"stage": stage, "title": title, **payload}


def summary_line(tool: str, installed: bool, version: Optional[str], markers: int,
                 created: list[str], already: bool) -> str:
    if not installed:
        return f"I couldn't install **{tool}** (bioconda only for now) — nothing was changed."
    if already and not created:
        return (f"**{tool}** {version or ''} is already installed and documented "
                f"({markers} HRR marker(s) still pending review). Nothing to do.")
    made = ", ".join(created) if created else "its fact sections"
    lead = "Installed" if not already else "Documented"     # 'already' here means install was present
    return (f"{lead} **{tool}** {version or ''} and created docs for {made}. Still **not runnable**: "
            f"{markers} HRR marker(s) need human review before it can be run.")
