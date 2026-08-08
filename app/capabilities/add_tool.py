"""add_tool — install + document a tool via the curator, streaming each stage.

Mirrors curator.bootstrap.bootstrap_and_curate but yields between steps so the chat shows a live
timeline: provision (install into the isolated curator-tools env) -> source (--help/docs) -> curate
each fact section -> persist workbook -> scaffold the machine-section HRR skeletons -> END at the
human-review gate. Installing via chat yields a DOCUMENTED but UN-RUNNABLE tool: the run_pipeline
judgment harness refuses to route it until a human replaces the HRR_ markers.

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
from shared import contracts_lib as cl

_ROLES = ("transfer", "enrich", "fix")
_PROVIDER_MAP = {"claude": "claude-cli", "ollama": "ollama"}   # UI name -> curator registry name
DEFAULT_SECTIONS = ["usage", "options"]


def _providers(ui_provider: Optional[str]):
    override = _PROVIDER_MAP.get(ui_provider or "")            # None -> registry auto
    return {r: registry.resolve(r, override=override) for r in _ROLES}


def plan(sections: Optional[list[str]] = None) -> list[str]:
    """Expected stage keys for the UI progress bar (matches what stage_events yields)."""
    sections = sections or DEFAULT_SECTIONS
    return ["provision", "source"] + [f"curate:{s}" for s in sections] + \
           ["persist", "scaffold", "hrr_gate"]


def stage_events(tool: str, ui_provider: str = "auto", sections: Optional[list[str]] = None,
                 binary: Optional[str] = None, url: Optional[str] = None) -> Iterator[tuple[str, dict]]:
    """Blocking generator: yield (stage, payload) as the curator provisions + documents `tool`."""
    sections = sections or DEFAULT_SECTIONS
    tool_dir = REPO / "bio-tools" / tool

    inst = ensure_installed(tool, binary=binary)
    if not inst.installed:
        yield "provision", {"tool": tool, "installed": False, "reason": inst.reason}
        return
    yield "provision", {"tool": tool, "installed": True, "version": inst.version,
                        "binary": inst.binary, "method": inst.method}

    src = sourcing.source_from_help(inst.binary or tool, env=ENV)
    if url:
        src = (src + "\n\n" + sourcing.source_from_url(url)).strip()
    yield "source", {"chars": len(src), "url": url}

    providers = _providers(ui_provider)
    outcomes = []
    for s in sections:
        ctx = {"source_version": inst.version} if s == "install" else {}
        o = curate_section(SectionTask(tool, s, src, example=None, ctx=ctx), providers)
        outcomes.append(o)
        items = len((o.obj or {}).get("options") or (o.obj or {}).get("examples") or [])
        yield "curate", {"section": s, "status": o.status, "fixes": o.attempts, "items": items}

    written = _persist_sections(tool_dir, outcomes)
    manifest = _write_manifest(tool_dir, tool, inst.version)
    yield "persist", {"sections_written": [Path(p).name for p in written],
                      "manifest": Path(manifest).name}

    scaffolded = write_machine_skeletons(tool_dir)
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
        "source": "Source (--help / docs)",
        "persist": "Persist workbook",
        "scaffold": "Scaffold machine sections",
        "hrr_gate": "Human-review gate",
    }
    title = f"Curate: {payload.get('section')}" if stage == "curate" else titles.get(stage, stage)
    return {"stage": stage, "title": title, **payload}


def summary_line(tool: str, installed: bool, version: Optional[str], markers: int) -> str:
    if not installed:
        return (f"I couldn't install **{tool}** (bioconda only for now) — nothing was changed.")
    return (f"Installed **{tool}** {version or ''} and drafted its fact sections. It's documented but "
            f"**not runnable yet**: the safety contract has {markers} HRR marker(s) for a human to "
            f"review before the judgment harness will route it.")
