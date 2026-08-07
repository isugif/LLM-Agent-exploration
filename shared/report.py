"""Render a pipeline report dict (as emitted by either track's run.py) into a readable markdown
summary. Used by both CLIs to write `report_summary.md` next to the JSON.

Handles all three terminal shapes: refused before compute, diagnosed crash, or evaluated output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_outputs(report: dict[str, Any], out_dir: str) -> None:
    """Write report.json + report_summary.md into out_dir (created if needed)."""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(report, indent=2))
    (d / "report_summary.md").write_text(to_markdown(report))


def to_markdown(report: dict[str, Any]) -> str:
    spec = report.get("spec") or {}
    route = report.get("route") or {}
    run = report.get("run_result") or {}
    verdict = report.get("verdict") or {}

    L: list[str] = []
    L.append(f"# Report summary — {report.get('tool', '?')}")
    L.append("")
    L.append(f"_Track: **{report.get('track','?')}** · LLM: `{report.get('llm_provider','?')}`_")
    L.append("")

    # --- request ---
    L.append("## Request")
    L.append(f"- **Question:** {spec.get('question','')}")
    if spec.get("deliverable") and spec["deliverable"] != spec.get("question"):
        L.append(f"- **Deliverable:** {spec['deliverable']}")
    L.append("")

    # --- onboarding: declared vs measured ---
    declared, measured = spec.get("declared") or {}, spec.get("measured") or {}
    if declared or measured:
        L.append("## Facts (onboarding)")
        L.append("| | Declared (stated) | Measured (probed) |")
        L.append("|---|---|---|")
        for key in sorted(set(declared) | set(measured)):
            L.append(f"| {key} | {declared.get(key,'—')} | {measured.get(key,'—')} |")
        if spec.get("disagreements"):
            L.append("")
            L.append("**Disagreements:** " + "; ".join(spec["disagreements"]))
        L.append("")

    # --- judgment ---
    L.append("## Routing (judgment)")
    L.append(f"- **Decision:** `{route.get('action','?')}` "
             f"(confidence {route.get('confidence','?')})")
    L.append(f"- **Rationale:** {route.get('rationale','')}")
    if route.get("precondition_failures"):
        L.append(f"- **Precondition failures:** {'; '.join(route['precondition_failures'])}")
    if route.get("boundary_hits"):
        L.append(f"- **Boundary checks:** {'; '.join(route['boundary_hits'])}")
    L.append("")
    if route.get("action") == "refuse":
        L.append("> Refused before compute — no tool was run.")
        L.append("")
        return "\n".join(L)

    # --- execution ---
    audit = run.get("audit") or {}
    L.append("## Execution")
    L.append(f"- **Command:** `{audit.get('cmd','')}`")
    L.append(f"- **Tool version:** {audit.get('tool_version','?')}")
    L.append(f"- **Exit code:** {run.get('exit_code','?')} · **{audit.get('seconds','?')}s**")
    L.append(f"- **Output dir:** `{run.get('output_dir','')}`")
    L.append("")

    # --- verdict ---
    L.append("## Results evaluation")
    L.append(f"- **Status:** `{verdict.get('status','?')}`"
             + ("  ⚠️ escalate to human curation" if verdict.get("escalate") else ""))
    metrics = verdict.get("metrics") or {}
    if metrics:
        L.append("")
        L.append("| Metric | Value | Assessment | Note |")
        L.append("|--------|-------|------------|------|")
        for name, m in metrics.items():
            tier = str(m.get("tier", "")).upper()
            L.append(f"| {name} | {m.get('value','')} | {tier} | {m.get('note','')} |")
    findings = verdict.get("findings") or []
    if findings:
        L.append("")
        L.append("**Findings:**")
        for f in findings:
            L.append(f"- {f}")
    if verdict.get("proposed_fix"):
        L.append("")
        L.append(f"**Proposed fix:** {verdict['proposed_fix']}")
    if verdict.get("explanation"):
        L.append("")
        L.append("## Explanation")
        L.append("")
        L.append(verdict["explanation"])
    L.append("")
    return "\n".join(L)
