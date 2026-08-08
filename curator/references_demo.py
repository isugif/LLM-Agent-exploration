"""Demo of the reference system: type detection, type-matched anchors, novel-tool curation, identify.

  python temp/curator/references_demo.py
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO))

from curator.providers import registry  # noqa: E402
from curator.references import anchors, sourcing  # noqa: E402
from curator.references.tool_types import classify, describe  # noqa: E402
from curator.stages.steps import SectionTask  # noqa: E402
from curator.nooa_curator.orchestrator import curate_section  # noqa: E402


def main() -> None:
    print("=== 1. classify installed tools from their real --help ===")
    types = {}
    for tool in ("fastqc", "multiqc", "hisat2"):
        src = sourcing.source_from_help(tool)
        types[tool] = classify(src) if src else "(not installed)"
        print(f"  {tool:8s} -> {types[tool]:18s} {describe(types[tool]) if src else ''}")

    print("\n=== 2. type-matched anchor selection (which reference tool shapes each section) ===")
    for tt in ("single_command", "aggregator", "multi_step"):
        who = anchors.anchor_source("input", tt)
        print(f"  input anchor for a {tt:16s} tool -> {who}")

    print("\n=== 3. curate a NOVEL tool (hisat2) usage from --help, AUTO type-matched anchor ===")
    prov = {r: registry.resolve(r, override="ollama") for r in ("transfer", "enrich", "fix")}
    src = sourcing.source_from_help("hisat2")
    task = SectionTask("hisat2", "usage", src, example=None, ctx={})   # example=None -> type anchor
    o = curate_section(task, prov)
    print(f"  hisat2 tool_type={o.tool_type}  usage status={o.status}  fixes={o.attempts}")
    for e in (o.obj or {}).get("examples", []):
        print("     cmd:", e["command"])

    print("\n=== 4. self-identify hisat2's github + homepage + paper (propose -> fetch-verify) ===")
    id_provider = registry.get("claude-cli") if registry.PROVIDERS["claude-cli"].is_available() \
        else registry.resolve("transfer", override="ollama")
    print(f"  identify provider: {id_provider.name}")
    info = sourcing.identify("hisat2", id_provider)
    for k in ("github", "homepage", "doi"):
        print(f"     {k:9s}: {info[k]}   (verified={info['verified'][k]})")
    print(f"     citation: {info['primary_citation']}")


if __name__ == "__main__":
    main()
