"""M3.3 verification (deterministic, no LLM): every clean section validates, harness still assembles.

  python temp/curator/verify_m33.py

Walks each tool's manifest, runs the schema gate + global + section checks over every context
section's clean yml, and confirms the harness can still assemble the machine contract.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from shared import contracts_lib as cl  # noqa: E402
from curator.validators.framework import run_checks  # noqa: E402

TOOLS = REPO / "bio-tools"


def main() -> None:
    fails = 0
    rows = []
    for tool in ("fastqc", "multiqc"):
        manifest = yaml.safe_load((TOOLS / tool / "manifest.yml").read_text())
        version = manifest["version"]
        for ref in manifest["sections"]:
            if ref["machine"]:
                continue                      # machine sections validated via the harness below
            raw = yaml.safe_load((TOOLS / tool / ref["path"]).read_text())
            ctx = {"source_version": version} if ref["name"] == "install" else {}
            results = run_checks(ref["name"], raw, ctx)
            bad = [r for r in results if not r.ok]
            fails += len(bad)
            status = "ok" if not bad else "FAIL: " + "; ".join(f"{r.check_id}({r.code})" for r in bad)
            rows.append(f"  {tool:8s} {ref['name']:13s} {len(results)} checks -> {status}")

    print("=== context-section validation (schema + global + section checks) ===")
    print("\n".join(rows))

    # harness still assembles the machine contract after the manifest changes
    print("\n=== harness contract assembly ===")
    for tool in ("fastqc", "multiqc"):
        c = cl.load_contract(tool)
        cl.validate_contract(c)
        print(f"  {tool}: id={c['id']} #preconditions={len(c['preconditions'])} "
              f"#boundaries={len(c['must_not_use'])} exp={c.get('expectations_ref')}")

    print(f"\nTOTAL context-check failures: {fails}")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
