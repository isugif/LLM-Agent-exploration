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

- **Data:** `bio-tools/<tool>/manifest.yml` + `clean/<section>.yml`. The `machine: true` sections
  (meta, execution, preconditions, must_not_use, failure_modes) are **assembled** into the runtime
  contract at load time by `shared/contracts_lib.py:load_contract`; context sections (install, usage,
  …) load on demand. One folder per tool is its single source of truth.
- **Code:** a parser (`shared/parsers/<tool>_parse.py`) and — only for a new input type — a probe
  (`shared/probes/<type>_probe.py`), both registered in `shared/tools/registry.py`.

Everything else is tool-agnostic: the contract's `execution.argv` drives a generic runner
(`shared/execution/runner.py`), and the scored metrics are the keys of the contract's expectation
table (no hardcoded metric list). Run with `--tool <id>`. Full guide: [ADD_A_TOOL.md](ADD_A_TOOL.md).
MultiQC is wired in as a second tool this way.

## The contract, on FastQC

FastQC is small and fast, so the whole loop runs in seconds. Its contract is **assembled** from the
`machine: true` sections listed in `bio-tools/fastqc/manifest.yml`
(`clean/{meta,execution,preconditions,must_not_use,failure_modes}.yml`) and deliberately fills the
gaps a documentation-style description leaves open:

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
(`shared/`). Only the *orchestration* differs — that is what the project compares. The per-harness
step logic (reconcile, build route, diagnose, score) lives once in `shared/harness_steps.py`; each
track's node functions / agent methods are thin wrappers over it, so behavioural parity is
structural rather than policed.

The per-checkpoint *wiring* is now single-sourced too: framework-neutral functions in
`shared/harnesses/{onboarding,judgment,execution,evaluation,diagnosis}.py` do one checkpoint each
(dict in, dict out), and the LangGraph nodes delegate to them. `shared/pipeline.py` sequences them
into an explicit order-guard, so the order `onboard → judge → refuse|run → evaluate|diagnose` is
enforced by code rather than emergent from graph edges / statement order. This is what the MCP
server and the agent loop (below) reuse.

| Harness | LangGraph (`langgraph_impl/`) | NOOA (`nooa_impl/`) |
|---|---|---|
| Onboarding | `harnesses/onboarding.py` node fn | `agents/onboarding.py` `OnboardingAgent` |
| Judgment | `harnesses/judgment.py` node fn | `agents/judgment.py` `JudgmentAgent` |
| Execution | `harnesses/execution.py` node fn | `run_tool` (generic runner) in `orchestrator.py` |
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

## The chat app (`app/`)

A split-screen web app (FastAPI + a vanilla-JS UI) is the interactive front end over the same
shared core. Free-text messages are classified into a typed **Intent** and dispatched by
deterministic code — the LLM routes and narrates, it never produces the facts. Wired capabilities:

- **describe_data** — probe a FASTQ and show measured facts + read-length / quality plots.
- **explain_tool** — answer about one documented tool, grounded in its `clean/` sections + live `--help`.
- **find_tool** — cross-tool discovery ("which tool takes fastq / is good for alignment") over a
  catalog built from every tool's manifest (`shared/catalog.py`, `shared/knowledge/categories.py`).
- **run_pipeline** — run a tool through the four harnesses, streaming each stage.
- **add_tool** — install + document a new tool via the curator (HRR-gated; not runnable until reviewed).
- **session_query** — recall this session's past runs (where the output went, what the verdict was),
  backed by a disk-persisted run-log (`app/session.py`, under `~/.bio_chat/sessions/`). A run's HTML
  report (FastQC/MultiQC) renders in an in-app **Report** tab.

## The MCP re-exposure + agent loop (the model-driven surface)

The hand-built intent router (`app/intent.py` + `app/resolve.py`) re-implements what a capable agent
does natively — intent, slot-filling, follow-ups, clarification, memory. It is being replaced by
letting the model *drive the harness as tools*. Two commitments keep that safe rather than a bypass:

- **One execution gate, made explicit.** `shared/pipeline.py` is the sole path that runs a tool
  (`onboard → judge → refuse | run → evaluate | diagnose`). It refuses before compute exactly as
  judgment does.
- **The trust boundary is the tool surface.** The model may chat, inspect/query the input folder and
  run outputs, and *request* tools — but the ONLY tool that executes anything is `run_tool`, which
  self-guards via `shared/pipeline`. No shell / arbitrary-code / write-outside-harness primitive is
  ever exposed to the model.

Two client surfaces sit over the same `shared/` core:

- **Web UI agent mode** — `app/agent_loop.py`, behind the `agent` flag on `POST /api/chat`. A
  provider-driven tool-use loop over `provider.extract(AgentAction, …)` (model-agnostic: Ollama or
  the Claude CLI, no native tool-calling API required). Tools: read-only `list_workdir` /
  `list_outputs` / `read_file` / `probe_data`, contract knowledge (`list_catalog` / `explain_tool` /
  `find_tool`), and the `run_tool` gate. `run_tool` is idempotent per turn and a repeat guard stops
  runaway loops. The legacy intent/resolve path stays the default until agent mode is proven.
- **Stdio MCP server** — `mcp_server/server.py` (`mcp[cli]==2.0.0`). Exposes the same harness as MCP
  tools so an external client (Claude Desktop/Code, or a local-model agent) supplies the
  intelligence, with the same self-guarding `run_tool`.

```
        Web UI (agent mode)                      MCP client (Claude Desktop/Code)
   POST /api/chat {agent:true}                          stdio (MCP)
                │                                             │
                ▼                                             ▼
     app/agent_loop.run_agent                   mcp_server/server.py  (9 tools)
     (provider.extract loop;                    probe · catalog · explain · find ·
      list_workdir/list_outputs/                 onboard · judge · run_tool ·
      read_file/probe/catalog/…)                 evaluate · diagnose
                │                                             │
   ═════════════│═══════════ TRUST BOUNDARY ═════════════════│═════════════
     model may request tools; ONLY run_tool executes; no shell exposed
                └────────────────────┬────────────────────────┘
                                     ▼
                     shared/pipeline.py  (order-guard)
             onboard → judge → REFUSE | run → evaluate | diagnose
                                     ▼
        shared/harnesses/*  →  harness_steps · contracts_lib ·
        execution/runner (subprocess, shell=FALSE) · probes · catalog
```

Design notes + the trust-boundary discussion that produced this: [`docs/mcp/`](mcp/).

## Not yet built (future milestones)

- **Judgment "retrieve & match"** — auto-selecting the tool by ranking candidate contracts against
  the spec. Today the tool is named with `--tool`; the pluggable contract library makes automatic
  selection the natural next step.
- The human-curation loop that turns novel escalations into new versioned contract entries.
- Real workflow composition (reuse vs. adapt vs. compose) across multiple tools.
- A shared incident library persisted across runs.
