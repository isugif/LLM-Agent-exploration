# Changelog — LangGraph track

All notable changes to the LangGraph implementation. Shared-layer changes are noted here too
(prefixed `shared:`) because this track depends on them; the same note appears in the NOOA
changelog so the two histories stay comparable.

Format: [Keep a Changelog](https://keepachangelog.com/). This project is pre-1.0.

## [0.3.0] — 2026-08-07

Shared-layer change (YAML structure); no track-specific code changed — the assembled contract keeps
the same shape both tracks already consumed, so all four harnesses and LangGraph↔NOOA parity are
unchanged.

### Changed
- shared: the contract moved from a monolithic `bio-tools/<tool>/contract.yml` to clean per-section
  ymls under `bio-tools/<tool>/clean/` + a per-tool `manifest.yml`. `contracts_lib.load_contract`
  now ASSEMBLES the runtime contract from the `machine: true` sections (meta, execution,
  preconditions, must_not_use, failure_modes). `contract.yml` deleted for fastqc + multiqc.
- shared: `validate_contract` validates each machine section against pydantic schemas
  (`shared/sections/schemas.py`) instead of the old JSON schema.

### Added
- shared: `shared/sections/schemas.py` — fact-only, LLM-readable pydantic section schemas (no Jekyll
  render tokens) + `Manifest`.
- shared: situational loading — `load_manifest` / `section_path` / `load_section` open one section on
  demand (e.g. `install.yml` only on an install error). Dedup: `interface`/`gotchas`/`operating_range`
  dropped from the machine contract (unused; they belong to context sections).
- bio-tools: clean machine sections + manifests for fastqc and multiqc; fixed the install version
  drift (single source now `0.12.1`, was `0.11.9` in the prose install.yml).
- shared: fact-only CONTEXT section schemas (`output`, `usage`, `options`, `dependencies`, `source`)
  and clean examples — fastqc {install,input,output,usage,options,dependencies,source,citations},
  multiqc {input,install,citations}. Consumed by the curator; harness behavior unchanged.

### Verified
- Deterministic suite 14 pass / 0 fail / 1 skip; both tracks still emit identical route/verdict.

## [0.2.0] — 2026-08-06

### Changed
- **Pluggable tools.** De-hardcoded the harness: `tool` added to `PipelineState`, `--tool` flag on
  the CLI, every `load_contract("fastqc")` → `load_contract(state["tool"])`, execution via the
  generic `run_tool`, evaluation via `get_parser(tool_id)` with scored metrics derived from the
  contract's expectation table (removed the hardcoded `SCORED` list). Onboarding probe is selected
  per tool via `get_probe`. Judgment's boundary-confirmation prompt is now tool-parameterized.
- shared: contracts moved to `bio-tools/<tool>/contract.yml` (single source of truth per tool);
  `contracts_lib` reads there and resolves `expectations_ref` against `shared/contracts/expectations/`.
- shared: new generic `shared/execution/runner.py` (contract-driven argv, list form — no shell);
  removed `shared/execution/fastqc_runner.py`. New `shared/tools/registry.py` (tool_id → parser +
  input probe). New `shared/probes/report_dir_probe.py` for aggregator inputs. Schema gained an
  `execution` block.

### Added
- MultiQC as a second tool (`bio-tools/multiqc/contract.yml` + `shared/qc/multiqc_parse.py`), wired
  in with **no track changes** — proof the pluggability works.
- `tests/` — committed fixtures per failure mode, `tests/cases.yaml`, and `tests/run_tests.py` which
  runs every case through both tracks and writes `tests/REPORT.md`. Deterministic mode is the gate.

### Verified
- FastQC regression + LangGraph↔NOOA parity unchanged. MultiQC happy path runs and scores.
- Deterministic suite: 14 pass / 0 fail / 1 skip. Full `--llm` suite: 16 / 16.

## [0.1.0] — 2026-08-06

### Added
- **Milestone 1: thin end-to-end four-harness slice on FastQC.**
- `state.py` — `PipelineState` TypedDict; state flows through nodes and is merged by LangGraph.
- `harnesses/onboarding.py` — probes the FASTQ (measured facts), LLM-extracts declared facts from
  the question, reconciles them, emits `Spec` with disagreements.
- `harnesses/judgment.py` — fit critic: evaluates contract preconditions + must-not-use boundaries
  (keyword pre-filter → LLM confirmation) against the deliverable; emits `RouteDecision` with the
  right to refuse.
- `harnesses/execution.py` — deterministic FastQC run node.
- `harnesses/diagnosis.py` — matches crash signals to contract `failure_modes`; escalates novel crashes.
- `harnesses/evaluation.py` — scores parsed metrics vs the expectation table; LLM explains anomalies
  but never changes the deterministic tier; refuses (`cannot_assess`) when output is unparseable.
- `graph.py` — `StateGraph` wiring the four harnesses with conditional edges
  (judgment→refuse/execute; execute→diagnosis/evaluation by exit code).
- `run.py` — CLI: `python -m langgraph_impl.run --fastq … --question … [--deliverable …]`.
- shared: contract schema + FastQC contract + rna-seq expectation table.
- shared: `fastq_probe`, `fastqc_runner` (+ audit record), `fastqc_parse`, `contracts_lib`
  (safe precondition eval, boundary match, metric scoring), `llm/provider` (Ollama + Null fallback),
  `data/fetch_virus_fastq.sh` (SARS-CoV-2 SRR11140744, subsampled to 10k reads).

### Fixed
- shared: metric scoring now best-first (`ok` wins over a wider `warn` band) and supports two-sided
  `not_between` for organism-dependent metrics like %GC — was mislabeling GC=48 as WARN.
- Judgment boundary-confirmation prompt clarified so "QC … before trimming" is not a false refusal
  (referencing a separate downstream step is not a must-not-use violation).

### Verified
- Happy path (SARS-CoV-2 reads): route=run, FastQC exit 0, verdict=anomaly with real metrics
  (quality 37.6 OK, GC 48 OK, duplication 82% FAIL-but-noted-normal-for-RNA).
- Refusal path: cohort-level deliverable → judgment refuses (`not_cohort_qc`), no compute.
- Diagnosis: OOM signal → known fix; novel crash → escalate; tool-missing → install hint.
- Non-FASTQ / empty input → refused pre-compute by the `input_is_fastq` precondition.
