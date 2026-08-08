"""Standardized skeletons for the MACHINE sections + the human-review (HRR) marker.

The machine sections (meta, execution, preconditions, must_not_use, failure_modes) are the enforceable
contract — expert judgment, not facts extractable from `--help`. So when a new tool is created we do
NOT auto-fill them; we lay down a standard SKELETON whose every value is prefixed `HRR_`
("Human Review Required"). The harness treats any `HRR_` marker in an assembled contract as
"not yet reviewed" and REFUSES to route the tool (see contracts_lib.is_reviewed / the judgment gate).
A human replaces the placeholders with reviewed content and removes the markers to activate the tool.

This makes the safety-critical half of the contract standardized, discoverable, and impossible to use
by accident before a human has vetted it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

HRR = "HRR_"   # marker: any HRR_ in a contract value => human review required

_HEADER = (
    "# ┌─ HUMAN REVIEW REQUIRED (HRR) ──────────────────────────────────────────────┐\n"
    "# │ Auto-scaffolded machine section — NOT trustworthy yet. Replace every HRR_   │\n"
    "# │ placeholder with expert-reviewed content and delete the markers. Until then │\n"
    "# │ the harness REFUSES to route this tool.                                     │\n"
    "# └────────────────────────────────────────────────────────────────────────────┘\n"
)

# skeleton content per machine section (values carry HRR_ markers so they're detectable)
MACHINE_SKELETONS: dict[str, object] = {
    "meta": {
        "summary": f"{HRR}one-paragraph description of what the tool does and its primary use",
        "expectations_ref": None,
    },
    "execution": {
        "argv": [f"{HRR}tool", "{input}", "{out_dir}"],
        "version_argv": [f"{HRR}tool", "--version"],
        "install_hint": f"{HRR}install command",
    },
    "preconditions": [
        {"id": f"{HRR}precondition_1", "assert": f"measured.format == '{HRR}format'",
         "severity": "block", "message": f"{HRR}what must hold about the input"},
    ],
    "must_not_use": [
        {"id": f"{HRR}boundary_1",
         "boundary": f"{HRR}an off-label use that would produce a silently-wrong result (expert judgment)",
         "keywords": [f"{HRR}keyword"]},
    ],
    "failure_modes": [
        {"id": f"{HRR}failure_1", "signal": f"{HRR}stderr substring that indicates this failure",
         "fix": f"{HRR}the known fix"},
    ],
}

MACHINE_ORDER = ["meta", "execution", "preconditions", "must_not_use", "failure_modes"]


def machine_manifest_entries() -> list[dict]:
    """Manifest section refs for the machine skeletons (all machine:true, always loaded)."""
    return [{"name": s, "purpose": f"{HRR}review-required machine section", "load_when": "always",
             "machine": True, "path": f"clean/{s}.yml"} for s in MACHINE_ORDER]


def write_machine_skeletons(tool_dir: str | Path, *, overwrite: bool = False) -> list[str]:
    """Write the 5 HRR machine skeleton ymls into <tool_dir>/clean/. Returns the paths written.

    Skips existing files unless overwrite=True (so it never clobbers already-reviewed sections).
    """
    clean = Path(tool_dir) / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    written = []
    for section in MACHINE_ORDER:
        path = clean / f"{section}.yml"
        if path.exists() and not overwrite:
            continue
        body = yaml.safe_dump(MACHINE_SKELETONS[section], sort_keys=False, default_flow_style=False)
        path.write_text(_HEADER + body)
        written.append(str(path))
    return written
