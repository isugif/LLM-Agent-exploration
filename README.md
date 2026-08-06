# LLM-Agent-exploration

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
shared/            framework-agnostic knowledge + execution (BOTH tracks import this)
  contracts/       contract schema, the FastQC contract, the expected-range table
  probes/          measured-facts probe for FASTQ
  execution/       deterministic FastQC runner (+ audit record)
  qc/              FastQC output parser
  contracts_lib.py load/validate contracts, safe precondition eval, metric scoring
  llm/             pluggable Ollama provider (LangGraph track)
  data/            fetch_virus_fastq.sh — small SARS-CoV-2 test dataset
langgraph_impl/    LangGraph track: StateGraph + node functions   (+ CHANGELOG.md)
nooa_impl/         NOOA track: Agent classes + plain orchestrator  (+ CHANGELOG.md)
docs/              ARCHITECTURE.md, COMPARISON.md
```

Guiding rule: knowledge about biology/tools lives in `shared/contracts/`; anything that *runs* a
tool lives in `shared/execution/`; anything an agent *decides* lives in a harness/agent file named
after the harness. Adding a tool = drop a contract yaml. Adding a check = add a metric row.

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

The LLM is only used for judgment-shaped steps; deterministic checks still run with Ollama off
(the pipeline reports `llm_provider: null` and degrades gracefully).

## Two changelogs

Each track keeps its own changelog so the divergence in orchestration effort is visible over time:
[`langgraph_impl/CHANGELOG.md`](langgraph_impl/CHANGELOG.md) ·
[`nooa_impl/CHANGELOG.md`](nooa_impl/CHANGELOG.md).
