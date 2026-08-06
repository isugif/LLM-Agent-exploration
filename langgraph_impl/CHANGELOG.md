# Changelog — LangGraph track

All notable changes to the LangGraph implementation. Shared-layer changes are noted here too
(prefixed `shared:`) because this track depends on them; the same note appears in the NOOA
changelog so the two histories stay comparable.

Format: [Keep a Changelog](https://keepachangelog.com/). This project is pre-1.0.

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
