# Session handoff — start here to resume

Single entry point to pick this project back up in a fresh session (even with agent memory cleared).
Everything referenced here is committed to the repo.

## What this project is

Exploring how to build **LLM agents for bioinformatics** two ways — **LangGraph** and **NVIDIA
Object-Oriented Agents (NOOA)** — on one shared architecture. The thesis: *bioinformatics fails
silently* (exit 0, wrong biology), so we make assumptions explicit as machine-readable **contracts**
and place **four harnesses** (onboarding → judgment → diagnosis/evaluation) around every run. A second
strand is the **curator**: an agent that writes the tool YAML the harness consumes.

Knowledge base (read these next):
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the four harnesses + contract concept.
- [`CURATOR.md`](CURATOR.md) — the curator: verified-property tables, token costs, gotchas, the
  fact/judgment boundary + HRR standard. **The lab notebook — keep it updated.**
- [`TRAITS.md`](TRAITS.md) — three-pillar trait composition (software/biology/tech).
- [`PRINCIPLES.md`](PRINCIPLES.md) — cross-cutting design rules incl. the **authority hierarchy**
  (which signal wins when two disagree) — the core silent-wrong-answer defense.
- [`COMPARISON.md`](COMPARISON.md) — LangGraph vs NOOA, incl. §8–9 (verdict + hybrid feasibility).
- [`ADD_A_TOOL.md`](ADD_A_TOOL.md) · [`BACKLOG.md`](BACKLOG.md) (prioritized next steps).

## How we collaborate (working agreement)

- **Who owns what:** the user is the bioinformatician — **domain/biology decisions are theirs**; the
  agent owns engineering. Surface domain choices; don't guess biology.
- **What's worked well:** a **shared-core** design (both frameworks are thin wrappers → fair comparison
  + easy extension); **deterministic-first, LLM-narrow** (runs offline); **verify-then-claim** (real
  runs + tables, not assertions); honest **"built vs deferred"**; **security-first** (no model-authored
  shell, whitelists, HRR gate); **persist findings in docs** so nothing is rediscovered.
- **The user's question style:** probing *"does this actually work / where / how"* that exposes gaps
  (did the harness read install.yml or did you? where did seqkit go? how are preconditions handled?).
  → **Self-audit and flag reality-vs-handwaving proactively, before being asked.**
- **Cadence:** plan-mode for non-trivial work; small verifiable increments ("not all in one go");
  commit + update CHANGELOGs + BACKLOG at milestones; concise, findings-first responses; connect work
  back to the premise (three pillars / four harnesses).
- **Recommended loop:** read this doc + BACKLOG → confirm env with the resume commands → pick a next
  step (or ask) → plan → build small → verify with a real run/table → commit + update
  CHANGELOGs/BACKLOG/CURATOR → flag caveats + offer follow-ups.

## Environment & resume

```bash
source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate nooa
export OLLAMA_MODEL=qwen2.5vl:7b     # local model (Ollama at :11434); `claude` CLI also present
```
- The `nooa` conda env provides `nooa` (0.0.8, NOT on PyPI) + langgraph + deps. Don't `pip install nooa`.
- Tools: harness tools live in `nooa` (fastqc/multiqc); the **curator** installs curation targets into a
  separate `curator-tools` env (hygiene).

**Verify the system is live:**
```bash
python tests/run_tests.py                     # harness suite → expect 14 pass / 0 fail / 1 skip
python -m langgraph_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "QC these reads before trimming"          # a harness run (fetch data first if missing:
                                                          # bash shared/data/fetch_virus_fastq.sh)
python curator/verify_m33.py                  # curator, deterministic (no LLM)
python curator/run_provision_demo.py          # curator: autonomous install→verify→gate→curate (needs Ollama)
```

## Repo map

```
langgraph_impl/ · nooa_impl/   the four-harness pipeline, two ways (+ CHANGELOG.md each)
shared/         contracts_lib.py (assemble contract from clean sections + compose traits),
                sections/ (schemas, scaffold=HRR), traits/{runtime,biology,domain}/,
                parsers/ execution/ probes/ llm/ data/
bio-tools/<tool>/   manifest.yml + clean/<section>.yml   (the LLM-readable source of truth)
curator/        the curator AGENT (now committed): providers/ stages/ references/ validators/
                langgraph_curator/ nooa_curator/ (+ their ARCHITECTURE.md), run_*.py demos
tests/          fixtures + run_tests.py → REPORT.md
docs/           this file + the knowledge base above
temp/           scratch only (gitignored): original sketches, images
```

## What's built (verified)

- **Four-harness pipeline** in both LangGraph + NOOA; parity on all paths; suite 14/0/1.
- **Pluggable tools** — add a tool = drop `bio-tools/<tool>/` data; no harness change. fastqc + multiqc wired.
- **LLM-readable clean sections + manifest**; the contract is *assembled* from `machine:true` sections.
- **HRR gate** — unreviewed machine contracts (`HRR_` markers) are refused by judgment.
- **Curator** — provision→classify→source-transfer→enrich→validate→(fix↻)→finalize, both frameworks;
  novel tools (hisat2/fastp/seqkit) curated from `--help`; DB3 anchor-leak defense (generalize→ground→
  fix); autonomous install gate. See CURATOR.md for the tables.
- **Trait composition** — runtime traits compose into contracts (fastqc inherits Java OOM→`-Xmx`);
  biology/domain knowledge library recorded (consumption deferred).
- **MCP re-exposure + agent loop** (the path forward, now the DEFAULT) — `shared/pipeline.py`
  order-guard + `shared/harnesses/*`; a stdio MCP server (`mcp_server/server.py`) and a model-agnostic
  agent loop (`app/agent_loop.py`) drive the harness as tools; only `run_tool` executes, no shell
  exposed. Chat routes to the agent when a model is reachable (Claude CLI preferred, else Ollama), else
  a deterministic `resolve.py` fallback. The LLM classifier (`app/intent.py`) is retired.
  **Phased plan + current status: [`mcp/PLAN.md`](mcp/PLAN.md).**

## Logical next steps (prioritized)

**Active path — MCP + agent loop (see [`mcp/PLAN.md`](mcp/PLAN.md) for detail):**
1. **Validate agent-loop quality** with a real model (Claude CLI / Ollama) on multi-file +
   tool-chaining tasks; tighten the system prompt if it mis-picks files.
2. Add the server-side **run state machine** (resume + HRR pause). LangGraph/NOOA are **kept** for the
   framework comparison (demoted in the README), not archived.
3. **Phase C** — interactive experiment-document contract (multi-file declared-vs-measured reconcile).

**Still-relevant from BACKLOG:**
4. **Data-trait consumption** (three pillars): classify platform/organism-domain at onboarding →
   attach traits → judgment cross-check (short-read aligner × Nanopore → refuse).
5. **Judgment "retrieve & match"** — auto-select the tool by ranking contracts (vs `--tool`).
6. **Batch multi-section transfer** (curator) — one prompt for all sections → ~4× token cut.

## Continuity risks / notes

- **Tool-env sprawl:** hisat2/fastp were manually installed into `nooa` (pre-provisioning); seqkit is
  correctly in `curator-tools`. Harmless, but tidy `nooa` if desired.
- **git push shows a spurious "fast-forward" hint** in this setup — pushes actually land (verify with
  `git rev-parse HEAD` vs `origin/<branch>`).
- Branch/state: the MCP + agent-loop work (Phase A+B core) is **merged to `main`**. Resume new work
  on a fresh branch (never commit on `main`). The `Agentic-Bioinformatics-Scientist` branch is merged.

## Acknowledgments

The original **`section-yml-curator`** skill — reimplemented here as the curator agent (LangGraph +
NOOA) — was **designed by Alex Badaczewska-Dawid ([@aedawid](https://github.com/aedawid))**, as part of
the **bio-omics workbook redesign**. This work reimplements it as an agent and adds the LLM-readable
clean-YAML redesign and the HRR human-review gate.
