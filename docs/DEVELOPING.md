# Developing

Repo layout, environment, how to add a tool, the curator, the LangGraph↔NOOA comparison, and tests.
Start with the [README](../README.md) for what the project is; this is the contributor's map.

## Environment

```bash
conda create -n bioharness python=3.12 -y
conda activate bioharness
pip install -r requirements.txt          # langgraph, langchain-core, pyyaml, jsonschema, requests,
                                         # fastapi, uvicorn, mcp[cli], pydantic
conda install -c bioconda fastqc -y      # FastQC 0.12.x
export OLLAMA_MODEL=qwen3.6:35b-a3b         # optional local model (Ollama :11434); the `claude` CLI also works
export OLLAMA_KEEP_ALIVE=-1              # (Ollama server setting) keep the model warm between calls
bash shared/data/fetch_virus_fastq.sh    # download + subsample the test FASTQ
```

- This env runs the **chat app**, the **MCP server**, and the **LangGraph track** — everything in the
  Quick start plus `python -m pytest` / `tests/run_tests.py`.
- **Local-model agent:** `ollama pull qwen3.6:35b-a3b` (a text/tool model, not a vision model); set
  `OLLAMA_KEEP_ALIVE` in the environment where `ollama serve` runs so the model isn't reloaded per
  call. Pick a specific model at runtime from the header dropdown or via `OLLAMA_MODEL`.
- The **NOOA track** (`python -m nooa_impl.run`) additionally requires the `nooa` package (0.0.8),
  which is **not on PyPI** and is installed separately — so that one comparison track is not
  reproducible from `requirements.txt` alone.
- The **curator** installs its curation-target tools into a separate `curator-tools` env (hygiene).

## Layout

```
bio-tools/         ONE folder per tool = its single source of truth
  fastqc/          manifest.yml + clean/<section>.yml (machine sections assembled into the contract)
  multiqc/         same layout — second tool, added with no harness changes
shared/            framework-agnostic knowledge + execution (BOTH tracks + the app + MCP import this)
  contracts_lib.py assemble contract from manifest, restricted-AST precondition eval, metric scoring
  contracts/expectations/  assay-keyed expected-range tables (referenced by expectations_ref)
  sections/schemas.py  pydantic schemas for every clean section (the validation gate)
  probes/          measured-facts probes (FASTQ; alignment; report-dir for aggregators)
  execution/       generic contract-driven runner (subprocess, shell=False; + audit record)
  parsers/         per-tool output parsers (fastqc, multiqc)
  harness_steps.py the four harnesses' deterministic step logic (framework-neutral)
  harnesses/       framework-neutral per-checkpoint step fns (onboarding/judgment/…)
  pipeline.py      the order-guard: onboard -> judge -> refuse|run -> evaluate|diagnose (single source)
  catalog.py + knowledge/  the tool catalog + purpose taxonomy (powers find_tool)
  tools/registry.py  tool_id -> parser + input probe
  llm/             pluggable Ollama / Claude-CLI / Null provider
  traits/          reusable constraints/knowledge (three pillars): runtime/ biology/ domain/
  data/            fetch_virus_fastq.sh — small SARS-CoV-2 test dataset
langgraph_impl/    LangGraph track: StateGraph + node fns (thin adapters over shared/harnesses)  (+ CHANGELOG.md)
nooa_impl/         NOOA track: Agent classes + plain orchestrator                                  (+ CHANGELOG.md)
curator/           LLM-driven curator: installs a tool + writes its clean sections (see CURATOR.md)
mcp_server/        stdio MCP server exposing the harness as tools (self-guarding run_tool)
app/               chat web app (FastAPI + JS UI); agent_loop.py = the default agent brain,
                   resolve.py = the deterministic no-model fallback
tests/             fixtures per failure mode + run_tests.py -> REPORT.md
docs/              ARCHITECTURE, COMPARISON, ADD_A_TOOL, BACKLOG, CURATOR, TRAITS, PRINCIPLES,
                   GLOSSARY, SESSION_HANDOFF; mcp/ = MCP-pivot design notes
```

## Adding a tool (it's data, not code)

Everything tool-specific lives in `bio-tools/<tool>/`; the harnesses are tool-agnostic.

**Adding a tool** = fill `bio-tools/<tool>/manifest.yml` + `clean/<section>.yml` (the curator can
auto-write the fact sections) + register a parser — see [`ADD_A_TOOL.md`](ADD_A_TOOL.md). **Adding a
QC check** = add a metric row to an expectation table. No harness/track code changes for either.
MultiQC was wired in exactly this way as the second tool.

## The curator

The **curator** (`curator/`) is an LLM-driven agent that provisions a tool and writes its clean YAML
sections, gated so a chat-installed tool is documented but **not runnable until a human reviews** its
safety contract (the HRR gate). Its verified properties, token costs, and findings are logged in
[`CURATOR.md`](CURATOR.md) so they don't have to be rediscovered.

```bash
python curator/verify_m33.py             # deterministic checks (no LLM)
python curator/run_provision_demo.py     # autonomous install → verify → gate → curate (needs Ollama)
```

## Advanced / research: compare LangGraph vs NOOA

The app and MCP server run the harness via `shared/pipeline.py`. The original research question —
LangGraph vs NOOA as orchestration frameworks (see [`COMPARISON.md`](COMPARISON.md)) — is exercised
through two per-track CLIs that sequence the *same* `shared/` harness two ways:

```bash
# a QC run, either track
python -m langgraph_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "QC these Illumina SARS-CoV-2 RNA-seq reads before trimming"
python -m nooa_impl.run     --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "QC these Illumina SARS-CoV-2 RNA-seq reads before trimming"

# a refusal (judgment stops it before compute)
python -m langgraph_impl.run --fastq shared/data/SRR11140744_10k.fastq.gz \
    --question "Assess these reads" \
    --deliverable "give me the overall cohort quality conclusion across all samples"

# a second tool (MultiQC) — point it at a directory of tool reports
python -m langgraph_impl.run --tool multiqc --fastq <dir_of_fastqc_reports> \
    --question "aggregate the FastQC reports for this run"
```

Both tracks degrade gracefully with Ollama off (they report `llm_provider: "null"`). Each track keeps
its own changelog so the divergence in orchestration effort is visible over time:
[`../langgraph_impl/CHANGELOG.md`](../langgraph_impl/CHANGELOG.md) ·
[`../nooa_impl/CHANGELOG.md`](../nooa_impl/CHANGELOG.md).

## Tests

```bash
# the four-harness benchmark across BOTH tracks -> tests/REPORT.md (exits nonzero on failure)
python tests/run_tests.py          # deterministic (no LLM)
python tests/run_tests.py --llm    # also runs the LLM-dependent boundary-refusal case

# the app + shared unit/integration suite
python -m pytest tests app/tests -q
```

`tests/REPORT.md` is a committed markdown table of every case × both tracks (happy / precondition
refusal / must-not-use refusal / anomaly / diagnosis / MultiQC). Fixtures are in `tests/inputs/`.

---

_Resuming work? [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) has env setup, resume commands, and
prioritized next steps; [`mcp/PLAN.md`](mcp/PLAN.md) has the current phased plan + status._
