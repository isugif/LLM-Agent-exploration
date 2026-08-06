# Changelog — NOOA track

All notable changes to the NOOA (NVIDIA Object-Oriented Agents) implementation. Shared-layer
changes are noted here too (prefixed `shared:`); the same note appears in the LangGraph changelog
so the two histories stay comparable.

Format: [Keep a Changelog](https://keepachangelog.com/). This project is pre-1.0.

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
