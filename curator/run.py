"""CLI entrypoint for the curator — provision a tool then curate its fact sections.

    python -m curator.run --tool star
    python -m curator.run --tool star --url https://github.com/alexdobin/STAR --full

Mirrors the tool-run surface (`python -m langgraph_impl.run ...`): one required `--tool`, sensible
defaults, a JSON summary, and a nonzero exit on failure so it composes in scripts. `tool` is the
bioconda package / workbook id (lowercase); the executable is auto-resolved even when it differs
(package `star` -> binary `STAR`), or pinned with `--binary`.

The curator fills only the CONTEXT (fact) sections. The enforceable MACHINE contract
(preconditions / must_not_use / failure_modes) is scaffolded with `HRR_` markers for a human to
author — the harness refuses to route the tool until they are removed (see docs/ADD_A_TOOL.md).
"""

from __future__ import annotations

import argparse
import json
import sys

from curator.providers import registry
from curator.bootstrap import bootstrap_and_curate

# The complete CONTEXT (fact) section set the curator can fill; `--sections` overrides this subset.
FULL_SECTIONS = ["install", "input", "output", "usage", "options", "dependencies", "source", "citations"]
DEFAULT_SECTIONS = ["usage", "options"]

_ROLES = ("transfer", "enrich", "fix")


def run_curator(tool: str, *, sections: list[str] | None = None, provider: str = "ollama",
                binary: str | None = None, url: str | None = None, propose: str | None = None,
                allow_install: bool = True) -> dict:
    """Provision `tool` and curate `sections`. Thin, importable wrapper over `bootstrap_and_curate`
    that resolves providers the way the demos do. Returns the bootstrap result dict."""
    providers = {r: registry.resolve(r, override=provider) for r in _ROLES}
    return bootstrap_and_curate(tool, sections or DEFAULT_SECTIONS, providers,
                                binary=binary, url=url, propose=propose, allow_install=allow_install)


def _summary(tool: str, res: dict) -> dict:
    """Compact, JSON-serializable view of a bootstrap result (drops provider objects / raw checks)."""
    inst = res["install"]
    out = {
        "tool": tool,
        "status": res["status"],
        "install": {"installed": inst.installed, "version": inst.version,
                    "binary": inst.binary, "method": inst.method, "reason": inst.reason},
    }
    if res["status"] == "ok":
        out["sections"] = [
            {"section": o.section, "status": o.status, "fixes": o.attempts,
             "items": len((o.obj or {}).get("options") or (o.obj or {}).get("examples") or [])}
            for o in res["outcomes"]
        ]
        out["manifest"] = res.get("manifest")
        out["sections_written"] = [str(p) for p in res.get("sections_written", [])]
        out["hrr_scaffolded"] = [str(p) for p in res.get("hrr_scaffolded", [])]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Provision + curate a tool's fact sections (curator)")
    ap.add_argument("--tool", required=True, help="bioconda package / workbook id (lowercase), e.g. star")
    ap.add_argument("--binary", default=None, help="probe-binary override; else auto-resolved (star->STAR)")
    ap.add_argument("--sections", default=",".join(DEFAULT_SECTIONS),
                    help=f"comma list of context sections (default: {','.join(DEFAULT_SECTIONS)})")
    ap.add_argument("--full", action="store_true", help=f"curate the full set: {','.join(FULL_SECTIONS)}")
    ap.add_argument("--provider", default="ollama", help="force one provider for all roles")
    ap.add_argument("--url", default=None, help="extra doc source (README/docs) appended to --help")
    ap.add_argument("--propose", default=None, help="proposed package name when it differs from the binary")
    ap.add_argument("--no-install", dest="allow_install", action="store_false",
                    help="do not install; fail if the tool is not already in the curator env")
    args = ap.parse_args()

    sections = FULL_SECTIONS if args.full else [s.strip() for s in args.sections.split(",") if s.strip()]
    res = run_curator(args.tool, sections=sections, provider=args.provider, binary=args.binary,
                      url=args.url, propose=args.propose, allow_install=args.allow_install)

    summary = _summary(args.tool, res)
    print(json.dumps(summary, indent=2))

    if res["status"] != "ok":
        print(f"\nBLOCKED: {res['install'].reason}", file=sys.stderr)
        sys.exit(1)

    unresolved = [s["section"] for s in summary["sections"] if s["status"] != "valid"]
    print(f"\nNext steps: fill the HRR_ machine contract (preconditions / must_not_use / failure_modes)"
          f" in bio-tools/{args.tool}/ and register a parser — see docs/ADD_A_TOOL.md.")
    if unresolved:
        print(f"Sections needing attention (not 'valid'): {', '.join(unresolved)}", file=sys.stderr)
    sys.exit(1 if unresolved else 0)


if __name__ == "__main__":
    main()
