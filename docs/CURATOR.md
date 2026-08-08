# Curator — findings & verified properties (reference log)

A durable record of what the `section-yml-curator` agent does, what's been **verified**, what it
**costs**, and the **gotchas** discovered — so we can reference rather than rediscover.

> **Where the code lives:** the curator agent is in `temp/curator/` (gitignored, not yet in the repo).
> Its **data** is committed: `shared/sections/schemas.py` (fact-only section schemas) and
> `bio-tools/<tool>/{manifest.yml,clean/*.yml}`. Per-framework loop write-ups:
> `temp/curator/{langgraph_curator,nooa_curator}/ARCHITECTURE.md`.
>
> **Keep this file updated** as we add features — treat it like a lab notebook for the curator.

## What it is (one paragraph)

The curator turns a tool's documentation **source** (`--help`, docs URL, or existing prose ymls) into
**clean, fact-only per-section YAML** validated against typed schemas. Pipeline:
`provision → classify → source-transfer (fill typed schema) → enrich → validate → (fix ↻) → finalize`.
Built in **both** LangGraph (conditional-cycle) and NOOA (bounded `while`) over one shared set of
stage functions (`temp/curator/stages/steps.py`), so the two tracks produce identical results.

## Verified properties

### Pipeline (M3.2, FastQC, local model `qwen2.5vl:7b`)
| Property | Result |
|---|---|
| Runs in both frameworks | ✅ LangGraph + NOOA |
| Track parity (identical outputs) | ✅ incl. the unresolved-citations case |
| Fix-loop fires + repairs drift | ✅ `install` 0.11.9 → 0.12.1 in 1 fix |
| No-fabrication guard | ✅ under-sourced citations → `SRC_MISS`, refused |
| Completes when adequately sourced | ✅ citations resolves once the link is in source |
| Harness suite unaffected | ✅ 14 pass / 0 fail / 1 skip |

### Novel tools curated from `--help` (no prior workbook)
| Tool | Type (classify) | Result |
|---|---|---|
| hisat2 | `multi_step` | usage (2 cmds) + options (47) `valid` |
| fastp | `single_command` | usage `valid`, 0 fixes |
| seqkit | `subcommand_toolkit` | usage + options `valid` (provisioned from scratch) |

### Type detection + anchors
| | |
|---|---|
| classify (from real `--help`) | fastqc→`single_command`, multiqc→`aggregator`, hisat2→`multi_step` |
| type-matched anchors | `single_command`→fastqc, `aggregator`→multiqc, `multi_step`→hisat2 |
| `identify()` self-search (Claude CLI) | hisat2 github + homepage + DOI all **fetch-verified** ✅ |

### Provisioning (install → verify → gate)
| Property | Result |
|---|---|
| Autonomous install | ✅ seqkit discovered 2.13.0 on bioconda, installed, curated — no manual step, no Claude |
| Gate blocks uninstallable | ✅ nonexistent tool → `blocked_install`, curation never runs |
| Idempotent | ✅ re-run → `already-present`, install skipped |
| Env hygiene | ✅ tool lands in `curator-tools`, not `nooa` |
| Security | ✅ `seqkit; rm -rf /` rejected; whitelisted managers/channels; `shell=False`; no model-authored commands |

## Measurements — token cost

One `transfer` call, fastp `options` (~9,590-char prompt; `options` is the largest section):
| Model | input | output | total |
|---|---|---|---|
| local `qwen2.5vl:7b` | 2,304 | 2,053 | **4,357** |
| Claude (CLI) | 3,485 | 1,469 | **4,954** |

Per **novel tool** (4 `--help` sections + a couple fix/enrich calls ≈ 6 LLM calls):
| Model | rough total |
|---|---|
| local | **~15–25k tokens** |
| Claude | **~20–30k tokens** |

**Biggest lever:** the `--help` source (~2.3k local / 3.5k Claude tokens) is **re-sent per section**.
Batching all sections into one prompt would cut per-tool input ~4× (in BACKLOG).

## Division of labor (who does what)

- **Local model** (`qwen2.5vl:7b`): all section extraction (transfer/enrich/fix/classify). Works
  because its job is *bounded* — fill a typed schema from provided source, guided by a generalized
  anchor, gated by deterministic checks + a fix-loop.
- **Harness** (deterministic code): schemas, validators, fix-loop, package discovery + install, and
  all shell execution. **The model never runs shell.**
- **Claude**: used only for `identify()` (repo/DOI recall). Optional.
- **Human/agent**: build the harness (one-time); review facts the checks can't verify (e.g. the
  hisat2 `-o` anchor leak, before grounding existed); author non-`--help` facts (install/citations)
  when no source provides them.

## Machine sections vs context sections — the fact/judgment boundary

The curator handles **only the fact half** of a tool's YAML. The enforceable **machine sections are
human-curated**, on purpose.

| | sections | source | who authors |
|---|---|---|---|
| **Context (facts)** | install, input, output, usage, options, dependencies, source, citations | tool `--help` / docs | **curator** (LLM, grounded, validated) |
| **Machine (judgment)** | meta, execution, **preconditions, must_not_use, failure_modes** | expert judgment (not in `--help`) | **human** (curator does NOT fill these) |

Why the machine contract stays human:
- **Not in `--help`** — no source to transfer from; the no-fabrication guard would have nothing to
  ground against.
- **Expert judgment** — `must_not_use` ("don't use FastQC as cohort QC; it's not a trimmer") and
  `preconditions` (what fails *silently*) are the bioinformatician knowledge the whole premise exists
  to capture.
- **Fabrication is catastrophic** — a wrong boundary/precondition *defeats the safety purpose*.

This is the premise's **human-curation loop**: the machine contract is curated judgment that becomes
versioned contract entries, not auto-generated documentation.

### The HRR standard (Human Review Required)

Creating a new tool lays down standardized **skeletons** for the 5 machine sections
(`shared/sections/scaffold.py`), every value prefixed **`HRR_`**. The harness treats any `HRR_` marker
in an assembled contract as "unreviewed" and **refuses to route the tool** until a human replaces the
placeholders and removes the markers.

- Detection: `shared/contracts_lib.py:is_reviewed / find_hrr_markers`.
- Gate: the **first** check in both judgment harnesses → `refuse` with "pending human review".
- Scaffolding: `write_machine_skeletons(tool)`; the curator's `bootstrap` calls it for new tools
  (skips already-reviewed files).

*Verified:* a scaffolded tool (13 `HRR_` markers) is refused by **both** tracks; reviewed tools
(fastqc/multiqc) route normally; suite unchanged (14/0/1).

## Guardrails — the DB3 "anchor must not supply facts" defense (3 layers)

DB3 (from the skill's `demos.md`): an anchor may shape *structure*, never a *fact*
(`TOOL_BEHAVIOR > SOURCE > SYNTAX > PATTERN > DEMO`). Defense:
1. **Generalize** (prevent) — `references/generalize.py` masks the anchor's tool-specific values to
   placeholders (`<tool> <flags> <input>`) for leak-prone sections before showing it. *Verified:*
   re-curating hisat2 usage with generalization → correct commands, **0 fixes, no `-o` leak**.
2. **Ground** (detect) — `validators/framework.py:usage_flags_grounded/options_flags_grounded`: every
   flag in a command/option must appear in the tool's `--help`. *Verified:* catches the `-o` leak
   (`UNGROUNDED_FLAG`); `-x/-U/-S` and the 56 real hisat2 options pass.
3. **Fix-loop** (repair) — a failed check feeds the specific error back for a targeted repair.

Complementary guards not yet built (in BACKLOG): LLM source-parity judge (semantic drift), executable
dry-run validation, keep `--help` untruncated for grounding.

## Gotchas discovered (don't rediscover)

- **Version drift is real and silent:** prose `install.yml` pinned `0.11.9` while the contract said
  `0.12.1` — the parity check catches it; the clean source is now single-truth.
- **Anchors leak facts:** fastqc's `-o` idiom appeared in a hisat2 command; structural checks pass it
  (it's a *factual* error). → grounding + generalization added.
- **Loose keyword classify:** `helper` signals (`sam/bam`, `filter`) false-matched fastqc (it merely
  *accepts* BAM). → tightened to purpose-specific phrases.
- **Grounding regex traps:** (a) truncating `--help` makes late flags look ungrounded — don't
  over-truncate; (b) flags are often bracketed in synopses (`[-S <sam>]`) — the lookbehind must allow
  a preceding delimiter, not just whitespace.
- **Version parsing traps:** a leading `\b` mis-parses `v2.13.0` as `13.0`; and a tool that errors on
  `--version` (seqkit uses the `version` subcommand) prints help full of spurious numbers — only parse
  **returncode-0** output, and try `--version`/`version`/`-v`/`-V`.
- **Facts hidden behind placeholders:** the primary citation link lives behind `[[CITATION]]` →
  index.yml, absent from the prose file — so citations can't resolve from prose alone (correctly
  refused).

## Known limits / v1 scope

- Provisioning is **bioconda-only**; pip-only / source-only tools → `blocked_install` (human follow-up).
- Anchors exist for `single_command` (fastqc), `aggregator` (multiqc), `multi_step` (hisat2);
  `subcommand_toolkit`/`helper` fall back to fastqc until samtools-style anchors are added.
- `classify` is a heuristic (called fastp `single_command` though it's a trimmer) — harmless for
  anchoring, but an LLM tie-breaker could sharpen it.

## Key files
- Pipeline: `temp/curator/stages/steps.py`; orchestration: `…/langgraph_curator/graph.py`, `…/nooa_curator/orchestrator.py`.
- References: `temp/curator/references/{tool_types,anchors,generalize,sourcing}.py`.
- Provisioning: `temp/curator/stages/provision.py`, `temp/curator/bootstrap.py`.
- Validators: `temp/curator/validators/framework.py`. Providers: `temp/curator/providers/*`.
- Schemas (committed): `shared/sections/schemas.py`. Demos: `temp/curator/run_*.py`.
