# Backlog

Enhancements we've identified but deferred. Not a commitment or an ordering — a place to park ideas
so they aren't lost. Add items as they come up; move to a milestone when we pick one up.

Status: 💡 idea · 📋 scoped · 🔨 in progress · ✅ done (link the commit/PR)

---

## Judgment "retrieve & match" — automatic tool selection

**Status:** 💡 idea

**What:** Today the tool is named explicitly (`--tool fastqc`). This item makes the judgment harness
*choose* the tool: parse the spec (organism, assay, data type, goal), retrieve candidate tool
contracts from the library, and rank them by fit — rejecting any whose contracts conflict with the
spec (the fit critic's real job). Emits a decision + rationale + confidence, and may route to
**reuse** (a validated pipeline covers it), **adapt** (swap a better-fit component), or **compose**
(assemble a novel arrangement).

**Why it matters:** it's the core agentic upgrade — moving from "run the tool I was told to" to
"decide the right tool up front." The pluggable contract library built in milestone 2 is exactly the
substrate this needs.

**Rough shape:** a retrieval step over `bio-tools/*/contract.yml` + a ranking/critic step
(deterministic contract checks first, LLM for tie-breaks). Structural ceiling: it can only reject
what a contract already declares — so it grows with the contract library.

---

## Deployment-recipe sections → separate informative folders for LLM ingestion

**Status:** 💡 idea

**What:** The render-only workbook sections that carry little reusable *fact* — `slurm`, `hpc`,
`container`, `binaries`, `docs`, `examples`, `task`, `workflow`, `custom`, `performance` — are NOT
converted to clean fact schemas in the current curator scope. Park them for later as their own
informative folders the LLM can ingest situationally, rather than forcing them into the per-tool
clean source.

**Why it matters:** these are environment/deployment concerns (cluster job scripts, container
recipes), not tool facts. They belong alongside *other* future informative folders the assistant can
draw on:
- **`bio-databases/`** — reference databases (what they are, when to use them).
- **`bio-data/`** — data-type knowledge (Illumina vs Nanopore characteristics, read profiles) to
  inform the analysis process / onboarding.
- **`hpc/` or `cloud/`** — help the LLM assist a user with *their* local HPC or cloud setup.

**Rough shape:** each is a manifest-indexed folder of clean, LLM-readable ymls loaded on demand
(same situational-loading pattern as the per-tool manifest). No harness dependency; purely additive
context. Convert the deployment workbook sections when one of these folders is built.

---

## Cutover follow-ups (from the machine-section split)

**Status:** 📋 scoped

Loose ends left after moving the contract to clean per-section ymls (harness cutover):

- **On-demand `install.yml` in diagnosis.** Diagnosis still reads `execution.install_hint`; wire it
  to open the `install` section via the manifest (`section_path`/`load_section`) on an install error,
  and drop the `install_hint` duplication. (Was the original M3.4 intent.)
- **Refresh the docs.** `docs/ADD_A_TOOL.md` and `docs/ARCHITECTURE.md` still say "drop a
  `contract.yml`"; update them to the manifest + `clean/<section>.yml` model (add-a-tool = fill the
  clean sections + manifest; the curator will automate this).
- **Remove the dead JSON schema.** `shared/contracts/schema/contract.schema.json` is no longer used
  (validation moved to pydantic in `shared/sections/schemas.py`); delete or repurpose it.
- **Regenerate the prose workbook ymls from the clean source.** The 22 render-template ymls are
  currently untouched and now stale vs the clean sections (e.g. install still shows `0.11.9`). Build
  the `render_workbook.py` step (M3.4) so the workbook becomes a generated view, then regenerate the
  hand-maintained prose files from the clean source.
- **MultiQC context sections.** MultiQC only has machine sections so far; add its clean
  `input`/`install`/`citations` in M3.3.

---

<!-- Template for new items:

## <short title>

**Status:** 💡 idea

**What:** ...

**Why it matters:** ...

**Rough shape:** ...

-->
