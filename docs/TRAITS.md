# Traits — the three pillars as composable constraints

Constraints in bioinformatics are mostly **shared**, not per-tool. A **trait** captures one such
constraint or piece of knowledge **once**, and many tools/runs **compose** it. This is how the three
pillars — **biology · sequencing technology · software** — enter the system without re-authoring the
same rule for every tool.

> **Leverage:** traits are *write-once-reuse*. You review the Java trait once; every Java tool inherits
> it. This *reduces* the human-review burden — a small library of reviewed traits, not N×M per-tool
> files.

## Two shapes of trait

| Shape | `kind` | Carries | The harness… | Example |
|---|---|---|---|---|
| **Enforceable** | `runtime` | `failure_modes`, `preconditions` | **acts on** it | Java → `OutOfMemoryError` → `_JAVA_OPTIONS=-Xmx` |
| **Interpretive** | `biology`, `domain` | `considerations` (+ `references`) | *will* surface it (future) | "eukaryotes have introns"; "a structure is a static snapshot of a dynamic molecule" |

Schema: `shared/sections/schemas.py:Trait`. Library: `shared/traits/<kind>/<name>.yml`.

## Where a trait attaches (this is the key distinction)

- **Tool traits** (software pillar) are **fixed for a tool** and compose into its **contract**.
  FastQC is *always* Java → its `manifest.yml` declares `runtimes: [java]` and `load_contract` merges
  the Java trait's `failure_modes` in (deduped by id; tool-specific wins).
- **Data traits** (technology + biology pillars) **vary per run** and attach to the **spec** at
  onboarding (Illumina vs Nanopore; RNA-seq; eukaryote vs prokaryote). The **judgment fit-critic** is
  where tool-contract meets data-traits.

Three-pillar mapping:

| Pillar | Trait kind | Attaches to | Status |
|---|---|---|---|
| **Software** | `runtime` (java, python…) | tool contract | ✅ **built** (Java, enforceable) |
| **Sequencing tech** | `platform` (illumina, nanopore…) | run spec (onboarding) | ⏳ deferred (data-trait consumption) |
| **Biology** | `biology`/`domain` (eukaryote, protein-structure…) | run spec / data type | 📚 **library built**, consumption deferred |

## The fit-critic payoff (why data-traits matter)

The composition makes silent-wrong-answers catchable *for free*:

> A short-read aligner's contract carries a `read_length` **precondition** (software trait). The run
> is measured as Nanopore ~10 kb reads (technology trait). Judgment → **refuse**: "runs but produces
> garbage." Neither trait alone catches it; their *composition* does.

## HRR interaction

Traits are the **reviewed library** (no `HRR_` markers). A tool that composes only reviewed traits
inherits reviewed constraints — so trait composition and the [HRR gate](CURATOR.md#the-hrr-standard)
pull the same direction: expert judgment is authored once, reviewed, and reused, not re-invented (and
never fabricated) per tool.

## What's built vs deferred

| | |
|---|---|
| ✅ **Enforceable runtime composition** | `shared/traits/runtime/java.yml`; `contracts_lib.load_contract` merges runtime `failure_modes`; FastQC declares `runtimes: [java]` and **dropped** its own `java_oom` (now inherited). Verified: fastqc has 4 failure_modes incl. inherited `java_oom`; multiqc (Python) inherits nothing; OOM diagnosis unchanged; suite 14/0/1. |
| 📚 **Interpretive knowledge library** | `shared/traits/biology/{eukaryote,prokaryote}.yml`, `shared/traits/domain/protein-structure.yml` — validated + loadable (`load_trait`, `list_traits`), each with `considerations` + `references`. **Recorded, not yet consumed.** |
| ⏳ **Deferred (BACKLOG)** | Data-trait *consumption*: classify a run's platform/organism-domain at onboarding, attach the traits to the spec, and surface `considerations` in results-evaluation / to the interpreter. Also: extend enforceable composition to `preconditions`/dependencies and add `platform` traits. |

## Adding a trait

1. Write `shared/traits/<kind>/<name>.yml` (validates against `Trait`): enforceable → `failure_modes`
   / `preconditions`; interpretive → `considerations` (+ `references`).
2. Enforceable runtime trait: reference it from a tool's `manifest.yml` `runtimes: [<name>]`.
3. It's the reviewed library — no `HRR_` markers; add `references` so the knowledge is auditable.

## Files
- Schema: `shared/sections/schemas.py:Trait`, `Manifest.runtimes`.
- Loader/compose: `shared/contracts_lib.py:load_trait / list_traits / load_contract`.
- Library: `shared/traits/{runtime,biology,domain}/*.yml`.
