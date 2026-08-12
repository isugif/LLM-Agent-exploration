# Bio Harness

Safe agentic bioinformatics — an LLM-agent harness that refuses silently-wrong analyses via machine-readable contracts + four checkpoints. MCP server + local models.

Bioinformatics fails **silently**: a pipeline exits zero but returns wrong biology because an
assumption was violated in the organism, the sequencing technology, or the software. We make those
assumptions explicit — every data type, database, tool, and workflow carries a **contract** stating
its preconditions, operating range, and must-not-use boundaries — then place **four checkpoints**
around the run. Onboarding turns the scientist's question into a structured spec, reconciling
declared facts against measured ones. Judgment routes it to a workflow whose contracts don't
conflict. Diagnosis explains crashes; results evaluation flags output outside expected ranges. Novel
cases escalate to human curation and return as versioned contracts, so the system's judgment
compounds.

We build this **agentic bioinformatician two ways** — with
[LangGraph](https://langchain-ai.github.io/langgraph/) and with
[NVIDIA Object-Oriented Agents (NOOA)](https://github.com/NVIDIA-NeMo/labs-OO-Agents) — on the
*same* architecture, so the frameworks can be compared honestly.
([NOOA GitHub](https://github.com/NVIDIA-NeMo/labs-OO-Agents) ·
[NOOA paper](https://arxiv.org/html/2607.20709v1))

## The four harnesses

1. **Onboarding** — turn the scientist's question into a spec, reconciling *declared* facts against
   *measured* facts probed from the files.
2. **Judgment** (fit critic) — route only to a tool whose contract doesn't conflict with the spec;
   refuse otherwise, before any compute.
3. **Diagnosis** — on a crash, match the failure against known failure modes.
4. **Evaluation** — on success, score output against expected ranges and flag anomalies.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Framework comparison:
[`docs/COMPARISON.md`](docs/COMPARISON.md). Every case × both tracks is benchmarked in
[`tests/REPORT.md`](tests/REPORT.md).

Milestone 1 implements this end-to-end on **FastQC** (small + fast for iteration).

## Layout

```
bio-tools/         ONE folder per tool = its single source of truth
  fastqc/          manifest.yml + clean/<section>.yml (machine sections assembled into the contract)
  multiqc/         same layout — second tool, added with no harness changes
shared/            framework-agnostic knowledge + execution (BOTH tracks import this)
  sections/schemas.py  pydantic schemas for every clean section (the validation gate)
  contracts_lib.py assemble contract from manifest, safe precondition eval, metric scoring
  contracts/expectations/  assay-keyed expected-range tables (referenced by expectations_ref)
  probes/          measured-facts probes (FASTQ; report-dir for aggregators)
  execution/       generic contract-driven runner (+ audit record)
  parsers/         per-tool output parsers (fastqc, multiqc)
  harness_steps.py the four harnesses' step logic, shared by both tracks
  catalog.py + knowledge/  the tool catalog + purpose taxonomy (powers find_tool)
  tools/registry.py  tool_id -> parser + input probe
  llm/             pluggable Ollama/Claude provider (LangGraph track)
  data/            fetch_virus_fastq.sh — small SARS-CoV-2 test dataset
  harnesses/       framework-neutral step fns (onboarding/judgment/execution/evaluation/diagnosis)
  pipeline.py      the order-guard: onboard -> judge -> refuse|run -> evaluate|diagnose (single source)
langgraph_impl/    LangGraph track: StateGraph + node fns (now thin adapters over shared/harnesses)
nooa_impl/         NOOA track: Agent classes + plain orchestrator  (+ CHANGELOG.md)
curator/           LLM-driven curator: installs a tool + writes its clean sections (see docs/CURATOR.md)
mcp_server/        stdio MCP server exposing the harness as tools (self-guarding run_tool)
app/               chat web app (FastAPI + JS UI) over the shared core; agent_loop.py = agent mode
tests/             fixtures per failure mode + run_tests.py -> REPORT.md
docs/              ARCHITECTURE.md, COMPARISON.md, ADD_A_TOOL.md, BACKLOG.md, CURATOR.md, TRAITS.md, PRINCIPLES.md, GLOSSARY.md
docs/mcp/          design notes for the MCP pivot + the chat-engine trust-boundary discussion
shared/traits/     reusable constraints/knowledge (three pillars): runtime/ biology/ domain/
```

The **curator** (`curator/`) is an LLM-driven tool that provisions a tool and writes its clean YAML
sections; its verified properties, token costs, and findings are logged in
[`docs/CURATOR.md`](docs/CURATOR.md) so they don't have to be rediscovered.

Guiding rule: everything tool-specific lives in `bio-tools/<tool>/`; the harnesses are
tool-agnostic. **Adding a tool = fill `bio-tools/<tool>/manifest.yml` + `clean/<section>.yml` (the
curator can auto-write the fact sections) + register a parser** (see
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

## Chat UI

A split-screen web app (chat left, ground-truth **facts + plots** right) is the interactive front
end. Type free text; an LLM classifies the request into a typed **Intent** and deterministic code
dispatches — the model routes and narrates, it never produces the facts.

```bash
pip install -r requirements.txt          # adds fastapi + uvicorn
python -m app                            # http://127.0.0.1:8000  (--port / --model / --workdir)
```

**Open the app in your data folder.** Data paths resolve against a **working directory** that
defaults to where you launched the app (a bare filename or relative path is looked up there, with
`shared/data/` as a fallback for the demo files). The `bin/abi` launcher opens the app "in" whatever
folder you're standing in — put `bin/` on your `PATH` or symlink it:

```bash
ln -s "$(pwd)/bin/abi" ~/.local/bin/abi   # once
cd /path/to/my/run && abi                 # opens the app with that folder as the working directory
```

From chat you can inspect or change it: *"what's in my folder?"* lists the data files grouped by
type; *"my data is in /path/to/run"* (or *"set my working directory to …"*) switches it. The active
folder shows in the header and is available at `GET/POST /api/workdir`.

Ask *"what can you tell me about `shared/data/SRR11140744_10k.fastq.gz`"* → the right panel fills with
the measured facts (format, read-length min/max/mode, Phred encoding, SE/PE hint), a read-length
histogram, and per-position quality. Pick **Ollama** or **Claude** in the model dropdown (Claude uses
your local `claude` login — no API key).

Wired intents:

- **describe_data** — profile a FASTQ (facts + plots).
- **explain_tool** — answer about a named tool, grounded in its docs + live `--help`.
- **find_tool** — cross-tool discovery: *"which tool takes fastq?"*, *"what's good for alignment?"*.
- **run_pipeline** — run a tool through the four harnesses, streaming each stage; the HTML report
  (FastQC/MultiQC) opens in the **Report** tab (or a new browser tab).
- **add_tool** — install + document a new tool via the curator (HRR-gated: documented but not
  runnable until a human reviews the safety contract).
- **session_query** — recall this session's past runs: *"where did I write the fastqc output?"*,
  *"what were the results?"*. Runs persist to a disk-backed log (`~/.bio_chat/sessions/`), and the
  **session picker** reloads a past session to continue or review it.
- **describe_workdir / set_workdir** — inspect the current working folder (*"what's in my folder?"*)
  or point it at your data (*"my data is in /path/to/run"*); see the launcher note above.

The LLM only classifies and narrates; deterministic code produces every fact, so the app degrades
gracefully with the model off.

### Agent mode + MCP server

The hand-built intent router is being replaced by letting a capable model **drive the harness as
tools**. The safety rule is that the model may chat, inspect/query the input folder and run outputs,
and *request* tools — but the only tool that executes anything is `run_tool`, which self-guards via
the `onboard → judge → refuse|run → evaluate|diagnose` pipeline. No shell / arbitrary-code path is
exposed.

- **Agent mode (UI):** tick the **agent** checkbox in the header. Your message drives
  `app/agent_loop.py` (a model-agnostic `provider.extract` tool-use loop) with `list_workdir`,
  `list_outputs`, `read_file`, `probe_data`, catalog/explain/find, and the `run_tool` gate — so
  *"run fastqc on each of the snf2 files"* or *"run rustqc on the output"* works without exact
  phrasing. The legacy intent path is still the default (agent mode is opt-in while it's proven).
- **MCP server:** point an external client (Claude Desktop/Code, or a local-model agent) at the same
  harness over stdio:
  ```bash
  pip install -r requirements.txt        # adds mcp[cli]==2.0.0
  python -m mcp_server.server            # stdio; register with your MCP client
  ```

Design notes + the trust-boundary discussion: [`docs/mcp/`](docs/mcp/). Full picture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#the-mcp-re-exposure--agent-loop-the-model-driven-surface).

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

---

_Resuming work on this repo? [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) has env setup,
resume commands, and prioritized next steps._
