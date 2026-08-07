# Architecture — the four-harness agentic bioinformatician

## The problem

Bioinformatics fails *silently*. A pipeline exits 0 and returns a biologically wrong answer
because an assumption was violated in one of three places:

- **Biological domain** — organism, ploidy, gene structure, eukaryote vs. prokaryote
- **Sequencing technology** — read type, strandedness, depth, chemistry
- **Software / analysis** — model assumptions, validated operating range, must-not-use boundaries

Crashes report themselves. Silent wrong answers do not — they propagate into publications. The
whole architecture exists to catch the silent ones.

## The mechanism: contracts + four checkpoints

Every component (tool, database, data type, workflow) carries a **contract**: a machine-readable
declaration of its interface, preconditions, validated operating range, must-not-use boundaries,
and known failure modes. A **harness** is a checkpoint where a contract's declarations are compared
against something. Four comparisons ⇒ four harnesses:

| Harness | Compares | Catches | When |
|---|---|---|---|
| **Onboarding** | user's declared world → measured facts → spec | mis-specified problem | before routing |
| **Judgment** (fit critic) | spec ↔ component contracts | predictable violations | before compute |
| **Diagnosis** | crash ↔ failure-mode signatures | hard failures | on exit ≠ 0 |
| **Evaluation** | output ↔ expected ranges | undocumented violations | on exit == 0 |

Two design commitments make this more than four LLM vibe checks:

1. **Onboarding measures, it doesn't just interview.** It probes the actual files for *measured*
   facts and reconciles them against the user's *declared* facts. A disagreement (declared
   paired-end over single-end files) is a first-class silent-error signal.
2. **Every harness has the right to refuse.** Judgment can say "no tool fits"; evaluation can say
   "I cannot assess this." A system that always routes will always produce something — and
   confident output on an unanswerable question is exactly the failure mode we're eliminating.

## Adding a tool (pluggable)

A tool is **data + two small functions**, no harness changes:

- **Data:** `bio-tools/<tool>/contract.yml` — the enforceable contract, living in the same folder as
  the tool's human-facing workbook ymls (single source of truth per tool).
- **Code:** a parser (`shared/parsers/<tool>_parse.py`) and — only for a new input type — a probe
  (`shared/probes/<type>_probe.py`), both registered in `shared/tools/registry.py`.

Everything else is tool-agnostic: the contract's `execution.argv` drives a generic runner
(`shared/execution/runner.py`), and the scored metrics are the keys of the contract's expectation
table (no hardcoded metric list). Run with `--tool <id>`. Full guide: [ADD_A_TOOL.md](ADD_A_TOOL.md).
MultiQC is wired in as a second tool this way.

## The contract, on FastQC

FastQC is small and fast, so the whole loop runs in seconds. Its contract lives at
`bio-tools/fastqc/contract.yml` and deliberately fills the gaps a documentation-style description
leaves open:

- **preconditions** — assertable expressions (`measured.n_reads_sampled > 0`) evaluated by a
  restricted expression evaluator (no `eval`), see `shared/contracts_lib.py`.
- **must_not_use** — off-label boundaries (not a cohort QC tool, not a trimmer, not a contamination
  caller) with keyword hints for a cheap deterministic pre-filter.
- **failure_modes** — crash signals + fixes the diagnosis harness matches against.
- **expectations_ref** — points at `shared/contracts/expectations/rnaseq_qc.yaml`, the expected-range
  table the evaluation harness scores metrics against.

## The loop

```
onboarding (probe + declare + reconcile)
  -> judgment (test preconditions & boundaries statically)     --refuse--> STOP (no compute)
      -> execution (run FastQC, capture audit trail)
          -> exit != 0 ? diagnosis (match failure_modes)
             exit == 0 ? evaluation (score vs expected ranges)  --anomaly--> findings (+ escalate)
```

## Two implementations, one architecture

The four harnesses are implemented twice, sharing 100% of the knowledge/execution layer
(`shared/`). Only the *orchestration* differs — that is what the project compares.

| Harness | LangGraph (`langgraph_impl/`) | NOOA (`nooa_impl/`) |
|---|---|---|
| Onboarding | `harnesses/onboarding.py` node fn | `agents/onboarding.py` `OnboardingAgent` |
| Judgment | `harnesses/judgment.py` node fn | `agents/judgment.py` `JudgmentAgent` |
| Execution | `harnesses/execution.py` node fn | `run_fastqc` called in `orchestrator.py` |
| Diagnosis | `harnesses/diagnosis.py` node fn | `agents/diagnosis.py` `DiagnosisAgent` |
| Evaluation | `harnesses/evaluation.py` node fn | `agents/evaluation.py` `EvaluationAgent` |
| Routing | conditional edges in `graph.py` | plain `if` in `orchestrator.py` |
| State | `PipelineState` TypedDict | local vars + agent fields |
| LLM | `shared/llm/provider.py` (Ollama HTTP) | nooa `PredictStrategy` (litellm→Ollama) |

Both hit the same Ollama model, so their outputs are directly comparable. See
[COMPARISON.md](COMPARISON.md).

## Where the LLM is (and isn't)

The LLM is used only at genuinely judgment-shaped points: parsing the question into declared facts,
confirming whether a keyword-matched boundary is a real violation, and explaining an anomaly in
plain language. Everything load-bearing — preconditions, crash matching, metric tiers — is
**deterministic**. So the pipeline still runs, and still catches real problems, with the LLM
switched off. The LLM sharpens judgment; it is never the thing that decides pass/fail.

## Not yet built (future milestones)

- **Judgment "retrieve & match"** — auto-selecting the tool by ranking candidate contracts against
  the spec. Today the tool is named with `--tool`; the pluggable contract library makes automatic
  selection the natural next step.
- The human-curation loop that turns novel escalations into new versioned contract entries.
- Real workflow composition (reuse vs. adapt vs. compose) across multiple tools.
- A shared incident library persisted across runs.
