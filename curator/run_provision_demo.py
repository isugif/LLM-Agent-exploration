"""Demo: autonomous provision -> verify -> curate, plus the gate.

  python temp/curator/run_provision_demo.py

1. Provision + curate an UNINSTALLED bioconda tool (seqkit) from scratch on the LOCAL model.
2. Show the GATE: a nonexistent tool -> blocked_install, no curation attempted.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO))

from curator.providers import registry
from curator.bootstrap import bootstrap_and_curate

TOOL = "seqkit"


def main() -> None:
    prov = {r: registry.resolve(r, override="ollama") for r in ("transfer", "enrich", "fix")}

    print(f"=== 1. provision + curate '{TOOL}' from scratch (local model) ===")
    res = bootstrap_and_curate(TOOL, ["usage", "options"], prov)
    inst = res["install"]
    print(f"  install: installed={inst.installed} version={inst.version}")
    print(f"  method : {inst.method}")
    if res["status"] == "ok":
        for o in res["outcomes"]:
            n = len((o.obj or {}).get("examples") or (o.obj or {}).get("options") or [])
            print(f"  curate  {o.section:8s} status={o.status} fixes={o.attempts} items={n}")
        u = next((o for o in res["outcomes"] if o.section == "usage"), None)
        if u:
            for e in (u.obj or {}).get("examples", []):
                print("     cmd:", e["command"])

    print("\n=== 2. the GATE: a nonexistent tool is blocked before any curation ===")
    res2 = bootstrap_and_curate("thisisnotarealtool_xyz", ["usage"], prov)
    print(f"  status: {res2['status']}")
    print(f"  reason: {res2['install'].reason}")
    print(f"  curation attempted: {'outcomes' in res2}")


if __name__ == "__main__":
    main()
