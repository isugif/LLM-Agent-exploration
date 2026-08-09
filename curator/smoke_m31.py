"""M3.1 smoke test: schemas + validators + provider + structured fill, end to end.

Run from anywhere:  python temp/curator/smoke_m31.py
Uses Ollama (override) so it's cheap and offline; the real pipeline will prefer Claude for transfer.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))            # shared.*
sys.path.insert(0, str(REPO))   # curator.*

import yaml  # noqa: E402

from shared.sections.schemas import InstallSection  # noqa: E402
from curator.validators.framework import run_checks  # noqa: E402
from curator.providers import registry  # noqa: E402
from curator.providers.structured import fill  # noqa: E402

CLEAN = REPO / "bio-tools/fastqc/clean"
PROSE_INSTALL = REPO / "bio-tools/fastqc/install.yml"
TRUE_VERSION = "0.12.1"


def line(t): print(f"\n=== {t} ===")


def main() -> None:
    # 1) hand-authored clean example passes every check
    line("1) clean install.yml vs checks (source_version=0.12.1)")
    raw = yaml.safe_load((CLEAN / "install.yml").read_text())
    for r in run_checks("install", raw, {"source_version": TRUE_VERSION}):
        print(f"  [{r.status}] {r.check_id} {r.code or ''} {r.detail}")

    # 2) drift is caught deterministically
    line("2) drift demo: same object, but source says 0.13.0")
    for r in run_checks("install", raw, {"source_version": "0.13.0"}):
        if not r.ok:
            print(f"  CAUGHT -> {r.check_id}: {r.code}: {r.detail}")

    # 3) migration + fill(): extract a CLEAN InstallSection from the STALE prose install.yml
    line("3) fill() clean InstallSection from the stale prose install.yml (0.11.9)")
    provider = registry.resolve("transfer", override="ollama")
    print(f"  provider: {provider.name}")
    example = InstallSection.model_validate(yaml.safe_load((CLEAN / "install.yml").read_text()))
    obj = fill(
        provider, InstallSection,
        instruction=("Extract the installation facts for the tool from the SOURCE. List each install "
                     "method with a plain command (strip any markdown code fences). Capture the "
                     "version, the verify command, and its expected output."),
        source=PROSE_INSTALL.read_text(),
        example=example,
    )
    print(f"  extracted version: {obj.version}  | methods: {[m.manager for m in obj.methods]}")

    # 4) the parity check flags the stale-source drift against the true version
    line("4) run checks on the extracted object against the TRUE version (0.12.1)")
    for r in run_checks("install", obj.model_dump(), {"source_version": TRUE_VERSION}):
        print(f"  [{r.status}] {r.check_id} {r.code or ''} {r.detail}")


if __name__ == "__main__":
    main()
