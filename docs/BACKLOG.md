# Backlog

Enhancements we've identified but deferred. Not a commitment or an ordering — a place to park ideas
so they aren't lost. Add items as they come up; move to a milestone when we pick one up.

Status: 💡 idea · 📋 scoped · 🔨 in progress · ✅ done (link the commit/PR)

---

## Workflow composition — chain tools + reusable intermediate artifacts

**Status:** 💡 idea

**What:** hisat2's index build is currently modeled as a **step inside** hisat2's own contract
(`execution.steps`: `hisat2-build` → `hisat2`, sharing `{out_dir}`) — the pragmatic first cut. The
richer model is **composition**: `hisat2_build` (fasta → index) and `hisat2` (reads + index → SAM) as
**separate capability contracts** (like `samtools_sort` / `samtools_markdup`), and the harness chains
them into a small pipeline, threading the intermediate. That unlocks:
- each step gets its **own four checkpoints** (a bad FASTA fails at `hisat2_build`'s diagnosis; a
  missing index refuses at `hisat2`'s preconditions) instead of being buried in one execution;
- the index becomes a **reusable, cacheable artifact** — build once, align many (build-vs-reuse
  decisioning);
- it generalizes the real thing: `align → sort → markdup → multiqc` as a composed workflow.

**Why deferred:** composition (a chaining engine, artifact passing, build-vs-reuse caching) is
milestone-sized; the multi-step `execution.steps` runner (shipped) is the stepping stone that proves
the intermediate-artifact plumbing composition needs. Do it when there are several multi-tool
workflows to justify it. Pairs with the "retrieve & match" item below (reuse / adapt / **compose**).

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
- **Refresh the docs.** ✅ Done — README (now leads with the premise), `docs/ADD_A_TOOL.md`,
  `docs/ARCHITECTURE.md`, `docs/COMPARISON.md`, `docs/TRAITS.md` updated to the manifest +
  `clean/<section>.yml` assembly model (no more `contract.yml`); the chat app + its capabilities are
  documented.
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

## Use rustqc for FASTQ profiling (faster than the stdlib probe)

**Status:** 💡 idea

**What:** Swap/augment the pure-Python FASTQ profiler (`shared/probes/fastq_probe.py:probe` /
`profile_fastq`, used by onboarding and the chat UI's `describe_data`) with
[`rustqc`](https://github.com/) — a Rust FASTQ QC tool — for the ground-truth measurements.

**Why it matters:** the stdlib probe samples the first N reads for speed, but a Rust reader can scan
the **whole file** far faster, giving exact (not sampled) length/quality distributions and richer
per-base metrics for the plots — with lower latency in the chat flow.

**Rough shape:** add a `rustqc` probe behind the same interface (`profile_fastq`-shaped dict:
facts + `length_hist` + `qual_by_pos`) so the UI/onboarding don't change; provision it via the curator
(bioconda/cargo) and fall back to the stdlib probe when it's not installed. Compare outputs against the
current probe to confirm parity before switching the default.

---

## GitHub repos as an install + release-freshness source (integrate `repoReleases`)

**Status:** 💡 idea

**What:** Let the user register a tool's **GitHub repo URL** as another source of truth, and wire in
the existing [`~/isugif/repoReleases`](https://github.com/isugif/repoReleases) tooling (a GitHub-API
fetcher: given a list of repo URLs it pulls every release's name + notes and the issues referenced in
each release body → `releases_data.json`). Two uses:

1. **Install source of truth** — treat the repo as a first-class provisioning input alongside
   bioconda. Today provisioning is **bioconda-only** (`curator/stages/provision.py`; pip-only /
   source-only tools → `blocked_install`). A repo URL gives install/build instructions (README,
   releases/tags, assets) for tools not on bioconda, and pins to a specific release tag.
2. **Release-freshness + regression check** — for an already-installed tool, compare the installed
   version against the latest GitHub release; if newer, surface the **release notes** and the
   **referenced issues** so the assistant can flag "major changes since your last analysis" or "a
   known issue was fixed/introduced." This feeds the **Diagnosis** harness (new failure modes appear
   in release notes/issues) and post-run **Evaluation** ("were results affected by a since-patched
   bug?").

**Why it matters:** closes the bioconda-only gap and turns version drift from a silent risk into an
actionable signal. The curator already has the adjacent pieces — `sourcing.source_from_url` (GitHub
README) and `identify()` (propose→fetch-verify repo/DOI) — so the repo URL slots into the existing
sourcing trust order; `repoReleases` adds the release/issue dimension on top.

**Rough shape:** (a) accept `--repo <url>` in `curator/run.py`, store it in the tool's `source`
section; (b) a release probe (port `getReleaseNotes.py`, token via `GITHUB_TOKEN` env — never
hardcoded) that maps installed version → latest release + notes + issues; (c) a freshness check the
harness can call on a known tool (gated, read-only). Start with the freshness check (low risk, no
install path changes); add repo-based install later since it reintroduces model/human-authored build
steps that the current whitelist-only provisioning deliberately avoids.

---

## LLM-technique enhancements (from a post-training / test-time-scaling review)

The following five items came out of reviewing the app against modern LLM techniques
(post-training, reasoning, test-time scaling, tool-use, agents, alignment, RL/fine-tuning). The
through-line: this app's deterministic verifiers (`curator/validators/framework.py:CheckResult`,
the expectation-table scoring, `failure_modes`, HRR gates) double as **verifiers, reward
functions, and eval graders** — which is exactly what makes these techniques cheap to adopt here.
Ordered by value/effort.

### 1 — Escalation ladder + validator-scored best-of-N (test-time scaling)

**Status:** 💡 idea

**What:** The curator's `validate → fix → revalidate` loop (`curator/stages/steps.py`) is already
primitive verifier-guided iteration. Upgrade it two ways: (a) an **escalation ladder** — ollama →
retry-with-error-feedback → `claude` (via the existing `ClaudeCLIProvider`) → HRR human — instead
of giving up after `max_fixes`; (b) **best-of-N**: sample N section drafts, score each with the
existing validators, keep the highest-scoring. Same pattern for the judgment boundary check
(`_confirm_boundary`): sample 3, majority-vote, escalate on disagreement.

**Why it matters:** generation is untrusted but *checking is trusted*, so spending more inference
compute is safe — you can only ever accept a draft your validators pass. Directly attacks the
weak-local-model quality ceiling on the one genuinely judgment-shaped call.

**Rough shape:** thread an attempt→provider ladder through `steps.py:fix` and the orchestrators
(`curator/{langgraph,nooa}_curator/`); reuse `providers/registry.py:ROLE_PREFERENCE` for the
provider order. Pairs with [Source-parity guards].

### 2 — Frozen eval set + scorecard for every LLM-touching step (alignment / LLM research hygiene)

**Status:** 📋 scoped

**What:** A small committed eval set that scores each LLM-shaped step across providers:
**refusal calibration** (should-refuse vs should-run prompts → over-refusal / under-refusal rates),
**DeclaredFacts extraction** (question → expected facts), **boundary confirmation**, and **curator
source-transfer** (help text → expected section). Emits a per-provider scorecard, extending the
existing `tests/REPORT.md` pattern.

**Why it matters:** prerequisite for trusting any model swap (qwen → llama → claude → a future
fine-tune) — turns "seems fine" into a measured number. **Under-refusal is the project's core
silent-failure nightmare**, and today only a single refusal case is tested.

**Rough shape:** a `tests/eval_cases.yaml` + runner mirroring `tests/run_tests.py`, run with
`--llm` against each provider; report refusal confusion matrix + extraction accuracy. Overlaps with
[Proactive parity / consistency gates].

### 3 — Bounded auto-remediation in Diagnosis (constrained agency)

**Status:** 💡 idea

**What:** Diagnosis currently matches a crash to a `failure_mode` and emits `proposed_fix`, then
stops (`shared/harness_steps.py:diagnose_run`). Close the loop: when the matched failure mode
carries a *mechanical* fix from the contract's own library (e.g. the Java runtime trait's
OOM → `-Xmx` bump), **apply it, rerun once, and escalate if it still fails** — fully audited.

**Why it matters:** this is the one place more agency pays off without abandoning the safety
posture — the fix comes from a human-reviewed contract, not a free-form model plan, and it's capped
at a single retry. Turns the incident library from advisory into acting.

**Rough shape:** extend `FailureMode` with an optional structured/re-runnable remedy (distinct from
the prose `fix`); add a bounded retry in the orchestrators after diagnosis; record the
attempt+outcome in the run audit. Depends on the enforceable side of
[Data-trait consumption] and [Unified error-code taxonomy].

### 4 — Function-calling intent router for the chat app (tool-use)

**Status:** 💡 idea

**What:** The chat UI's intent router (`app/intent.py`) is a hand-rolled classifier with
deterministic backstops. Replace/augment it with native **function-calling**: expose each
capability (`describe_data`, `run_pipeline`, `add_tool`, `explain_tool`) as a tool schema and let
the model route via structured tool selection, keeping the deterministic backstops as a fallback.

**Why it matters:** more robust and extensible routing (adding a capability = adding a schema), and
it's the natural substrate for the [Judgment "retrieve & match"] item — tool selection is itself a
tool-use problem. Note the app's deliberate inversion (pipeline decides *when* to call the LLM)
stays intact in the harnesses; this is only about the chat front-door.

**Rough shape:** define per-capability tool schemas; use the provider's function-calling (or
structured-output) path in `app/api/routes_chat.py`; keep `app/intent.py`'s rules as the
low-confidence fallback.

### 5 — Harvest training data now; LoRA a small local model later (fine-tuning / RLVR)

**Status:** 💡 idea

**What:** Every run already produces schema-constrained input→output pairs with **automatic
labels**: (question → DeclaredFacts), (deliverable + boundary → violates/reason), (help text →
validated section JSON, labeled pass/fail by the validators), plus **free human labels** from HRR
review decisions. Log these as a dataset now (zero cost); when volume justifies it, LoRA-fine-tune a
small local model on the app's actual tasks.

**Why it matters:** the LLM calls here are tiny, typed extractions — exactly what a fine-tuned 3–8B
model does well, at lower latency and fully offline. The validator-produced labels make
**RL-from-verifiable-rewards** unusually feasible if training is ever pursued; near-term, use the
reward signal for *selection* (item 1), not training.

**Rough shape:** an opt-in logging hook that writes prompt/response/label rows (redacted, no
secrets) to a local dataset dir; revisit fine-tuning as a separate milestone once there's volume.
Gated by [item 2]'s eval harness (you need the scorecard to prove a fine-tune actually wins).

---

## Batch / multi-file run inputs (globs, lists, "all fastqs in a dir")

**Status:** 📋 scoped

**What:** Today `run_pipeline` runs **one** input per turn — you must name each file separately. Let a
run request name **many** inputs: a glob (`run fastqc on wt*`), a comma/space list
(`run fastqc on wt1.fastq.gz, wt2.fastq.gz`), or a directory sweep (`run fastqc on all fastqs in
<dir>`). Expand the pattern against the **working directory** (`app/workdir.py`) into a concrete file
list, then run the four-harness pipeline **once per file**, streaming each with a per-file header, and
finish with an aggregate summary (N ok / M refused / …). Each still lands in its own session run dir —
so a subsequent `run multiqc` (now defaulting to the session `runs/` dir) aggregates them.

**Why it matters:** the replicated designs we build for (3 WT + 3 snf2Δ) are inherently multi-file;
one-at-a-time is the main friction in the QC→align→aggregate flow. Pairs naturally with the MultiQC
session-dir default already shipped.

**Rough shape:** (a) resolver: a `inputs_in(message)` that returns a **list** — glob via
`Path(workdir).glob`, split a delimited list, or enumerate a dir by extension; prefer the workdir,
keep the single-file path intact when only one matches. (b) `run_pipeline.stage_events` (or the route)
loops over the list, minting a session run dir per file; the UI already keys output/activity per turn,
so emit a per-file sub-header + a final roll-up `prose`. (c) guard the count (confirm before running,
say, >8). Deferred from the MultiQC-dir-input fix; requested next.

<!-- Template for new items:

## <short title>

**Status:** 💡 idea

**What:** ...

**Why it matters:** ...

**Rough shape:** ...

-->
