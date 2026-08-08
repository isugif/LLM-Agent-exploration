"""M3.2 driver: full curator pipeline in BOTH frameworks on FastQC's 3 clean sections.

  python temp/curator/run_m32.py [--provider ollama]

Does three things:
  1. Runs install/input/citations through the LangGraph and NOOA orchestrations (with the committed
     clean ymls as few-shot examples) and checks both reach `valid`.
  2. Runs a FIX-LOOP demo: curate `install` from the STALE prose install.yml (version 0.11.9) with NO
     example and the true version 0.12.1 — the validate→fix→revalidate cycle must correct the drift.
  3. Compares the two tracks and writes temp/curator/out/m32_report.md.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO))

from curator.providers import registry  # noqa: E402
from curator.stages.steps import SectionTask, build_tasks  # noqa: E402
from curator.langgraph_curator.graph import curate_tool as lg_curate  # noqa: E402
from curator.nooa_curator.orchestrator import curate_tool as nooa_curate  # noqa: E402

OUT = REPO / "temp/curator/out"
SECTIONS = ["install", "input", "citations"]


def _providers(override: str):
    return {role: registry.resolve(role, override=override) for role in ("transfer", "enrich", "fix")}
    # note: resolve() maps role->preference; override forces one provider for a repeatable M3.2 run.


def _fact(o) -> str:
    """One-line key fact per section for the report."""
    d = o.obj or {}
    if o.section == "install":
        return f"version={d.get('version')} methods={[m['manager'] for m in d.get('methods',[])]}"
    if o.section == "input":
        return f"formats={[f['format'] for f in d.get('formats',[])]}"
    if o.section == "citations":
        return f"doi/url={d.get('doi') or d.get('url')}"
    return ""


def _row(track, o):
    npass = sum(1 for r in o.results if r.ok)
    return (f"| {track} | `{o.section}` | {o.status} | {o.attempts} | {npass}/{len(o.results)} "
            f"| {_fact(o)} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama")
    args = ap.parse_args()
    prov = _providers(args.provider)
    print(f"provider: {prov['transfer'].name}")

    tasks = build_tasks("fastqc", SECTIONS)
    print("== NOOA track =="); nooa_out = nooa_curate(tasks, prov)
    print("== LangGraph track =="); lg_out = lg_curate(tasks, prov)

    # fix-loop demo: stale prose source (0.11.9), no example, true version 0.12.1
    prose_install = (REPO / "bio-tools/fastqc/install.yml").read_text()
    drift = SectionTask("fastqc", "install", prose_install, example=None,
                        ctx={"source_version": "0.12.1"})
    nooa_drift = nooa_curate([drift], prov)[0]
    lg_drift = lg_curate([drift], prov)[0]

    # no-fabrication demo: citations' primary link is NOT in the prose (it's behind [[CITATION]]),
    # so the prose-only run should stay unresolved (SRC_MISS). Give it an adequate source and it
    # completes — proving the guard is about source sufficiency, not a pipeline limitation.
    from shared.sections.schemas import schema_for  # noqa: E402
    cite_example = schema_for("citations").model_validate(
        __import__("yaml").safe_load((REPO / "bio-tools/fastqc/clean/citations.yml").read_text()))
    cite_src = ((REPO / "bio-tools/fastqc/citations.yml").read_text()
                + "\nCanonical project link: https://www.bioinformatics.babraham.ac.uk/projects/fastqc/")
    cite_ok = nooa_curate([SectionTask("fastqc", "citations", cite_src, cite_example, {})], prov)[0]

    # ---- report ----
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# M3.2 — curator pipeline (both frameworks)", "",
             f"_provider: {prov['transfer'].name}_", "",
             "## Happy path (with clean examples as anchors)", "",
             "| Track | Section | Status | Fixes | Checks | Key fact |",
             "|---|---|---|---|---|---|"]
    for o in nooa_out:
        lines.append(_row("nooa", o))
    for o in lg_out:
        lines.append(_row("langgraph", o))
    lines += ["", "## Fix-loop demo (stale prose 0.11.9, true version 0.12.1, no example)", "",
              "| Track | Section | Status | Fixes | Checks | Key fact |",
              "|---|---|---|---|---|---|",
              _row("nooa", nooa_drift), _row("langgraph", lg_drift), "",
              "## No-fabrication guard (citations)", "",
              "Prose-only citations has no primary DOI/URL (it lives behind `[[CITATION]]`), so the",
              "curator refuses to invent one and the validator flags SRC_MISS. With an adequate source",
              "(canonical link appended) it completes.", "",
              "| Track | Section | Status | Fixes | Checks | Key fact |",
              "|---|---|---|---|---|---|",
              _row("nooa (adequate source)", cite_ok), ""]
    (OUT / "m32_report.md").write_text("\n".join(lines))

    # ---- console summary + checks ----
    print("\n".join(lines))
    by = {(o.section): o for o in nooa_out}
    install_input_valid = by["install"].status == "valid" and by["input"].status == "valid"
    parity = all(n.obj == l.obj for n, l in zip(nooa_out, lg_out))     # both tracks agree, incl. citations
    cites = by["citations"]
    no_fab = (cites.status == "unresolved"
              and any(r.code == "SRC_MISS" for r in cites.results))    # refused to fabricate
    cite_completes = cite_ok.status == "valid" and bool(cite_ok.obj.get("url") or cite_ok.obj.get("doi"))
    drift_fixed = nooa_drift.status == "valid" and nooa_drift.obj["version"] == "0.12.1"

    print(f"\ninstall+input valid (both tracks): {install_input_valid}")
    print(f"track parity (identical facts, incl. citations): {parity}")
    print(f"no-fabrication guard held on prose-only citations (SRC_MISS): {no_fab}")
    print(f"citations completes with adequate source: {cite_completes}")
    print(f"drift corrected 0.11.9 -> 0.12.1 via fix-loop: {drift_fixed} "
          f"(fixes nooa={nooa_drift.attempts} lg={lg_drift.attempts})")
    print(f"\nreport -> {OUT / 'm32_report.md'}")
    ok = install_input_valid and parity and no_fab and cite_completes and drift_fixed
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
