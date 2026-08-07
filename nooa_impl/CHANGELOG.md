# Changelog — NOOA track

All notable changes to the NOOA (NVIDIA Object-Oriented Agents) implementation. Shared-layer
changes are noted here too (prefixed `shared:`); the same note appears in the LangGraph changelog
so the two histories stay comparable.

Format: [Keep a Changelog](https://keepachangelog.com/). This project is pre-1.0.

## [0.3.0] — 2026-08-07

Shared-layer change (YAML structure); no track-specific code changed — the assembled contract keeps
the same shape both tracks already consumed, so all four harnesses and NOOA↔LangGraph parity are
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
- **Pluggable tools.** De-hardcoded the agents: `run_pipeline(..., tool_id=...)` and `--tool` flag;
  `JudgmentAgent`/`DiagnosisAgent`/`EvaluationAgent` take `tool_id` and load their contract from it.
  Execution via the generic `run_tool`; evaluation via `get_parser(tool_id)` with scored metrics
  derived from the contract's expectation table (removed `SCORED`). Onboarding probe selected per
  tool via `get_probe`. `confirm_boundary` is now tool-parameterized (args, not a fixed docstring).
- shared: contracts moved to `bio-tools/<tool>/contract.yml`; generic `shared/execution/runner.py`;
  `shared/tools/registry.py`; `shared/probes/report_dir_probe.py`; schema `execution` block
  (see the LangGraph changelog for the shared-layer detail).

### Added
- MultiQC as a second tool, wired in with **no agent/orchestrator changes**.
- `tests/` suite + `tests/REPORT.md` (shared with the LangGraph track; runs both).

### Fixed
- Boundary-confirmation prompt: the docstring-as-prompt wording under-specified the decision rule, so
  `qwen2.5vl:7b` let a cohort-level deliverable through where LangGraph refused it. Tightened the
  docstring to state the rule as pointedly as the LangGraph prompt → NOOA now refuses consistently
  (3/3), full `--llm` suite 16/16. See docs/COMPARISON.md §6.

### Verified
- FastQC + MultiQC happy paths at parity with the LangGraph track. Deterministic suite 14/0/1.

## [0.1.0] — 2026-08-06

### Added
- **Milestone 1: thin end-to-end four-harness slice on FastQC.** Uses the real `nooa` package
  (0.0.8) — no shim needed. Agentic methods run via nooa's native `PredictStrategy` against a local
  Ollama model routed through litellm (`ollama_chat/<model>`).
- `llm.py` — builds a (lazy) nooa `UnifiedLLM` for Ollama; reports reachability so the orchestrator
  can fall back to deterministic-only when Ollama is down.
- `agents/onboarding.py` — `OnboardingAgent`: deterministic `probe_file`/`reconcile` methods +
  agentic `parse_question` (`@strategy(PredictStrategy())`, DeclaredFacts return type).
- `agents/judgment.py` — `JudgmentAgent`: deterministic precondition/boundary checks + agentic
  `confirm_boundary`; `route` composes the RouteDecision with the right to refuse.
- `agents/diagnosis.py` — `DiagnosisAgent`: fully deterministic crash-signal matching.
- `agents/evaluation.py` — `EvaluationAgent`: deterministic scoring vs the expectation table +
  agentic `explain`; the LLM never changes the deterministic tier.
- `orchestrator.py` — composes the four agents with ORDINARY PYTHON control flow (`if` over
  dataclasses); this is NOOA's answer to LangGraph's StateGraph.
- `run.py` — CLI identical to the LangGraph track: `python -m nooa_impl.run --fastq … --question …`.
- shared: (same shared knowledge/execution layer as the LangGraph track — see that changelog).

### Fixed
- Agents that have no agentic methods (e.g. DiagnosisAgent) still require an LLM at construction in
  nooa. Build the `UnifiedLLM` lazily and pass it to every agent; gate only the *calls* on Ollama
  reachability. Previously `DiagnosisAgent()` raised "No LLM available".

### Verified
- Happy path (SARS-CoV-2 reads): route=run, FastQC exit 0, verdict=anomaly — identical metric
  tiers to the LangGraph track (quality OK, GC OK, duplication FAIL, overrepresented WARN).
- Refusal path: cohort deliverable → refuse (`not_cohort_qc`), matching LangGraph.
- Offline degradation (bad OLLAMA_HOST): provider=null, declared={}, no false refusal, correct
  deterministic tiers — identical to LangGraph's NullProvider behavior.
