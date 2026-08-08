# LLM-Agent-exploration

> **Resuming?** Start with [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) — env, resume commands,
> what's built, and prioritized next steps.


Building an **agentic bioinformatician** two ways — with [LangGraph](https://langchain-ai.github.io/langgraph/)
and with [NVIDIA Object-Oriented Agents (NOOA)](https://github.com/NVIDIA-NeMo/labs-OO-Agents) — on
the *same* architecture, so the frameworks can be compared honestly.

* [NOOA GitHub](https://github.com/NVIDIA-NeMo/labs-OO-Agents) · [NOOA paper](https://arxiv.org/html/2607.20709v1)

## The premise

Bioinformatics fails **silently**: a pipeline exits 0 and returns wrong biology because an
assumption was violated in the organism, the sequencing technology, or the software. We make those
assumptions explicit as machine-readable **contracts**, and place **four harnesses** (checkpoints)
around every run:

1. **Onboarding** — turn the scientist's question into a spec, reconciling *declared* facts against
   *measured* facts probed from the files.
2. **Judgment** (fit critic) — route only to a tool whose contract doesn't conflict with the spec;
   refuse otherwise, before any compute.
3. **Diagnosis** — on a crash, match the failure against known failure modes.
4. **Evaluation** — on success, score output against expected ranges and flag anomalies.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Framework comparison:
[`docs/COMPARISON.md`](docs/COMPARISON.md).

Milestone 1 implements this end-to-end on **FastQC** (small + fast for iteration).

## Layout

```
bio-tools/         ONE folder per tool = its single source of truth
  fastqc/          workbook ymls (install/hpc/usage/...) + contract.yml (the enforceable contract)
  multiqc/         same layout — second tool, added with no harness changes
shared/            framework-agnostic knowledge + execution (BOTH tracks import this)
  contracts/       schema/ + expectations/ (assay-keyed expected-range tables)
  probes/          measured-facts probes (FASTQ; report-dir for aggregators)
  execution/       generic contract-driven runner (+ audit record)
  qc/              per-tool output parsers (fastqc, multiqc)
  tools/registry.py  tool_id -> parser + input probe
  contracts_lib.py load/validate contracts, safe precondition eval, metric scoring
  llm/             pluggable Ollama provider (LangGraph track)
  data/            fetch_virus_fastq.sh — small SARS-CoV-2 test dataset
langgraph_impl/    LangGraph track: StateGraph + node functions   (+ CHANGELOG.md)
nooa_impl/         NOOA track: Agent classes + plain orchestrator  (+ CHANGELOG.md)
tests/             fixtures per failure mode + run_tests.py -> REPORT.md
docs/              ARCHITECTURE.md, COMPARISON.md, ADD_A_TOOL.md, BACKLOG.md, CURATOR.md, TRAITS.md, PRINCIPLES.md
shared/traits/     reusable constraints/knowledge (three pillars): runtime/ biology/ domain/
```

The **section-yml-curator** agent (an LLM-driven tool that writes the clean YAML) lives in `temp/`
(not yet in the repo); its verified properties, token costs, and findings are logged in
[`docs/CURATOR.md`](docs/CURATOR.md) so they don't have to be rediscovered.

Guiding rule: everything tool-specific lives in `bio-tools/<tool>/`; the harnesses are
tool-agnostic. **Adding a tool = drop `bio-tools/<tool>/contract.yml` + register a parser** (see
[`docs/ADD_A_TOOL.md`](docs/ADD_A_TOOL.md)). Adding a QC check = add a metric row to an expectation
table. No harness/track code changes for either.

## Setup

```bash
conda activate nooa                      # env that provides nooa==0.0.8
pip install -r requirements.txt          # langgraph, langchain-core, pyyaml, jsonschema, requests
mamba install -c bioconda fastqc         # FastQC 0.12.x
ollama serve &                           # local model server
export OLLAMA_MODEL=qwen2.5vl:7b         # any local model works
bash shared/data/fetch_virus_fastq.sh    # download + subsample the test FASTQ
```

## Run

Both tracks share one CLI surface:

```bash
# LangGraph
python -m langgraph_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "QC these Illumina SARS-CoV-2 RNA-seq reads before trimming"

# NOOA
python -m nooa_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "QC these Illumina SARS-CoV-2 RNA-seq reads before trimming"
```

Trigger a **refusal** (judgment stops it before compute):

```bash
python -m langgraph_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "Assess these reads" \
    --deliverable "give me the overall cohort quality conclusion across all samples"
```

A **second tool** (MultiQC) with the same CLI — point it at a directory of tool reports:

```bash
python -m langgraph_impl.run --tool multiqc --fastq <dir_of_fastqc_reports> \
    --question "aggregate the FastQC reports for this run"
```

The LLM is only used for judgment-shaped steps; deterministic checks still run with Ollama off
(the pipeline reports `llm_provider: null` and degrades gracefully).

## Tests

```bash
python tests/run_tests.py          # deterministic (no LLM) — writes tests/REPORT.md, exits nonzero on failure
python tests/run_tests.py --llm    # also runs the LLM-dependent boundary-refusal case
```

`tests/REPORT.md` is a committed markdown table of every case × both tracks (happy / refusal /
precondition-block / anomaly / diagnosis / MultiQC). Fixtures are in `tests/inputs/`.

## Two changelogs

Each track keeps its own changelog so the divergence in orchestration effort is visible over time:
[`langgraph_impl/CHANGELOG.md`](langgraph_impl/CHANGELOG.md) ·
[`nooa_impl/CHANGELOG.md`](nooa_impl/CHANGELOG.md).
