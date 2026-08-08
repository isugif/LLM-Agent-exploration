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

## Source-parity guards for curated facts (beyond flag-grounding)

**Status:** 📋 scoped

**What:** Prevent/catch the curator copying a FACT from a few-shot anchor instead of the source (a
DB3 violation — e.g. fastqc's `-o` leaking into a hisat2 command). Two guards are **already built**
in `curator/`:
- **flag-grounding** (`validators/framework.py:usage_flags_grounded / options_flags_grounded`) —
  every flag in a generated command/option must appear in the tool's `--help`; failures drive the
  fix-loop.
- **anchor-generalization** (`references/generalize.py`) — mask the anchor's tool-specific facts to
  placeholders (`<tool> <flags> <input>`) for leak-prone sections before showing it to the model.

Complementary guards to add later:
- **LLM source-parity judge** — a second-pass check that reads the generated section + the SOURCE and
  lists any claim/flag/value not supported by source. Catches *semantic* drift the flag-grounding
  regex can't: wrong values (`-t 999`), wrong flag semantics, invented notes. Run only after the
  deterministic checks pass; feed failures into the fix-loop.
- **Executable dry-run validation** — for tools that support it, confirm generated flags are actually
  accepted (parse `--help`, or a no-op/`--dry-run` invocation). Tool-specific + side-effect risk, so
  opt-in per tool.
- **Keep source complete for grounding** — don't over-truncate `--help` (an earlier bug made late
  flags look ungrounded). For very long help, chunk/summarize rather than cut, so grounding sees all
  real flags.

**Why it matters:** the anchor system is a big accuracy lever, but anchors can smuggle facts. These
guards make the curator's "no fabrication beyond source" promise enforceable, not aspirational.

---

## Data-trait consumption (technology + biology pillars)

**Status:** 📋 scoped

**What:** The trait *mechanism* and an interpretive knowledge library exist (`shared/traits/`,
[`docs/TRAITS.md`](TRAITS.md)) — runtime traits already compose into contracts (Java proof). What's
missing is **consuming data traits** at run time:
- **Classify** a run's platform (Illumina/Nanopore/…) and organism-domain (eukaryote/prokaryote) at
  onboarding, from measured + declared facts.
- **Attach** the matching traits to the spec.
- **Judgment cross-check:** tool `operating_range`/`must_not_use` × data traits (e.g. short-read
  aligner × Nanopore read-length → refuse — the fit-critic payoff).
- **Results-evaluation / interpreter:** surface each trait's `considerations` (e.g. "eukaryotes have
  introns → use a splice-aware aligner") alongside the verdict.
- Add `platform` traits (`shared/traits/platform/{illumina,nanopore}.yml`) and extend enforceable
  composition beyond `failure_modes` to `preconditions`/dependencies.

**Why it matters:** this is the higher-value half of the three-pillars idea — turning recorded
knowledge into checks and interpretation. Needs the onboarding classification step first.

---

## Stress-test the framework edges (LangGraph vs NOOA) + hybrid

**Status:** 💡 idea

**What:** At current size neither framework has a decisive advantage (they're thin wrappers over the
shared core; see [`docs/COMPARISON.md`](COMPARISON.md) §8–9). Two concrete experiments would surface
the real differences, each aligned with a roadmap feature:
- **LangGraph HITL checkpoint** — build the **human-curation loop** with LangGraph `interrupt()` +
  a checkpointer: pause at an HRR/novel case, persist state, resume after human review. This is where
  LangGraph should clearly win.
- **NOOA CodeAct compose** — build the **compose route** (assemble a novel multi-tool pipeline) with
  NOOA `CodeActStrategy`, letting the model author the orchestration. This is where NOOA should win.

**Hybrid:** once an edge is confirmed, adopt a single **hybrid** build — LangGraph as the outer
skeleton (state/persistence/interrupts/fan-out) calling **NOOA agents at nodes** that benefit
(compose/CodeAct, typed extraction, large-data pass-by-reference). Seam discipline: checkpoint at
LangGraph boundaries, treat a NOOA sub-call as atomic, marshal only serializable results into
checkpointed state. Make the **human-curation loop the first hybrid**.

**Why it matters:** tells us whether to keep two parallel implementations (comparison) or converge on
one hybrid (production) — and which framework owns which part.

---

## Unified error-code taxonomy → incident library

**Status:** 💡 idea

**What:** Codes are stable but scattered — `CheckResult.code` (curator), `failure_modes` ids +
signals (diagnosis), HRR, route-refuse rationales, `blocked_install`. Consolidate into **one typed
taxonomy** shared across harnesses, then build the premise's **incident library**: diagnosis matches a
run against known codes → proposes the known fix; results-evaluation escalates a *novel* code through
human curation into a new versioned entry.

**Why it matters:** stable codes are what make the fix-loop, diagnosis, and the "system judgment
compounds" loop work. See [`docs/PRINCIPLES.md`](PRINCIPLES.md) §4.

---

## Golden-file tests for the deterministic extraction layer

**Status:** 📋 scoped

**What:** The parsers/validators that turn tool output into facts (`shared/parsers/{fastqc,multiqc}_parse.py`,
and the metric-scoring path) are the highest-risk surface — a mis-parsed metric silently flips a
verdict. Add **golden-file tests**: commit a small real tool output (a `fastqc_data.txt`, a
`multiqc_general_stats.txt`) and assert the parser yields the exact expected metric dict; add edge
cases (missing module, empty file, odd formatting).

**Why it matters:** rewriting the skill's checks and building the curator's grounding/version parsing
surfaced several *self-inflicted* regex bugs. This layer is trusted but unverified — the exact
silent-wrong-answer failure the project exists to prevent. See [`docs/PRINCIPLES.md`](PRINCIPLES.md) §5.

---

## Proactive parity / consistency gates (CI)

**Status:** 💡 idea

**What:** Make redundancy-policing first-class rather than reactive (the skill only wrote a
drift-checker *after* the drift bit it). Add checks to `tests/`:
- **Both tracks agree** — LangGraph vs NOOA emit identical spec/route/verdict on the same input
  (currently asserted only in the curator's `run_m32`; do it for the harness too).
- **References resolve** — every manifest `runtimes:` trait exists; every `expectations_ref` file
  exists; every manifest section `path` exists and validates against its schema.
- **(Later) clean-source ↔ rendered workbook** parity once the render step exists.

**Why it matters:** turns a whole class of drift bugs from "caught once" into "can't happen". See
[`docs/PRINCIPLES.md`](PRINCIPLES.md) §2.

---

<!-- Template for new items:

## <short title>

**Status:** 💡 idea

**What:** ...

**Why it matters:** ...

**Rough shape:** ...

-->
