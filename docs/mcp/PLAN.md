# Plan: MCP harness + model-driven agent loop

The durable version of the phased plan for pivoting the chat surface to a self-guarding harness the
model drives as tools. Promoted from an ephemeral planning doc so it survives a repo rename / fresh
clone. Design notes that led here: [`abundant-pondering-wave.md`](abundant-pondering-wave.md),
[`UI_chatengine.md`](UI_chatengine.md), [`UI_chatengine_discussion_summary.md`](UI_chatengine_discussion_summary.md).

## Status snapshot (2026-08-12)

- **Phase A — MCP server + self-guarding gate: DONE, merged to `main`.**
- **Phase B — model-agnostic agent loop: CORE DONE, merged (agent mode is OPT-IN).**
  Remaining: flip the default, retire the intent/resolve brain, archive the orchestrator trees, add
  the run state machine.
- **Phase C — interactive experiment-document contract: NOT STARTED.**

Tests at merge: 101 pass; parity gate 14/0 (deterministic).

## Context / goal

The hand-built intent router (`app/intent.py` + `app/resolve.py`) re-implements what a capable model
does natively (intent, slot-filling, follow-ups, memory). The **moat** is the four checkpoints +
contract×trait knowledge + probes, already isolated in `shared/`. So this is a **re-exposure, not a
rewrite**: let the model drive the harness as tools, but force **all execution through one
self-guarding gate**.

### Locked decisions
- **Trust boundary = the tool surface.** The model may chat + inspect/query the folder and outputs +
  *request* tools, but the ONLY tool that executes is `run_tool` (self-guards via `shared/pipeline`).
  No shell / arbitrary-code / write-outside-harness is ever exposed. Hard boundary, built phased.
- **Model-agnostic brain.** Provider-swappable via `provider.extract`: Claude `claude` CLI
  (subscription, no API tokens) by default, Ollama optional. No native tool-calling API required.
- **Orchestrators.** Lift the LangGraph node bodies into framework-neutral `shared/harnesses/*`
  (DONE — nodes now delegate), then eventually **archive** (not delete) `langgraph_impl/` +
  `nooa_impl/` so the future LangGraph-MCP-client / framework comparison stays cheap to restart.

Full architecture + trust-boundary diagram: [`../ARCHITECTURE.md`](../ARCHITECTURE.md#the-mcp-re-exposure--agent-loop-the-model-driven-surface).

---

## Phase A — MCP server + the gate  ✅ DONE

- `shared/harnesses/{onboarding,judgment,execution,evaluation,diagnosis}.py` — framework-neutral
  step functions lifted from the LangGraph nodes (which now delegate to them; behaviour preserved).
- `shared/pipeline.py` — explicit **order-guard** (`onboard → judge → refuse|run → evaluate|diagnose`),
  replacing the ordering that was emergent from graph edges / statement order.
- `mcp_server/server.py` — stdio MCP server (`mcp[cli]==2.0.0`) exposing exactly: `probe_data`,
  `list_catalog`, `explain_tool`, `find_tool`, `onboard_experiment`, `judge`, `run_tool`,
  `evaluate_output`, `diagnose_failure`. `run_tool` self-guards; nothing else executes.
- Tests: `tests/test_pipeline.py`, `tests/test_mcp_server.py`.

---

## Phase B — model-agnostic agent loop  ◑ CORE DONE, tail remaining

**Done:**
- `app/agent_loop.py` — provider-driven tool-use loop (`AgentAction` via `provider.extract`). Tools:
  read-only `list_workdir` / `list_outputs` / `read_file` / `probe_data`, knowledge `list_catalog` /
  `explain_tool` / `find_tool`, and the `run_tool` gate. Idempotent `run_tool` + repeat guard +
  deterministic close-out prevent runaway loops.
- Wired behind the `agent` flag on `POST /api/chat` (`app/api/routes_chat.py`); UI header has an
  **agent** toggle (`app/ui/index.html` + `app.js`). Legacy intent/resolve path is still the DEFAULT.
- Tests: `tests/test_agent_loop.py`; app smoke `app/tests/test_app_smoke.py::test_chat_agent_mode_sse`.

**Remaining (resume here):**
1. **Validate loop quality with a real model** (Claude CLI + Ollama) across multi-step, multi-file,
   and tool-chaining tasks (e.g. align → `list_outputs` → rustqc). Tighten the system prompt if the
   model still mis-picks files.
2. **Flip the default** to agent mode, then **retire `app/intent.py` + `app/resolve.py`**. Preserve
   `resolve.py`'s path extractors (`path_in`, `aln_in`, `fasta_ref_in`, `gtf_in`) as plain utilities
   if any tool still needs them.
3. **Archive the orchestrator trees** (Phase A3, deferred): once the legacy `run_pipeline` capability
   no longer imports `langgraph_impl.graph`, move `langgraph_impl/` + `nooa_impl/` to `archive/` and
   update `docs/COMPARISON.md` (server = tool interface; orchestration = client layer). Note
   `tests/run_tests.py` also imports both trees — update it too.
4. **Server-side run state machine** (`draft→onboarded→judged_ok→refused→running→completed`, bound to
   a server-issued run id): the framework-neutral home for resume + the HRR human-review pause — where
   "replay/restart/HITL" live now that LangGraph is out of the hot path.
5. **Provider loop tradeoff:** the subscription `claude` CLI is single-shot, so the loop is
   hand-rolled ReAct; if quality is inadequate, fall back to the Anthropic Messages API (token-billed,
   native tool-use loop). Both keep the boundary hard.

---

## Phase C — interactive experiment-document contract  ○ NOT STARTED

The highest-value, least-proven piece. Turn onboarding into an interactive experiment-design contract:
- Richer schema: extend `shared/models.py:Spec` → an `ExperimentDoc` (organism, assay, samples[],
  replicates, layout, reference, per-file measured facts, disagreements).
- **Multi-file** declared-vs-measured reconciliation (net-new logic over `harness_steps.reconcile`):
  "you said 3 replicates but I see 6 files with 2 aliases", "you said paired-end, these look SE".
- Versioned persistence in the session dir (`app/session.py`); an MCP **prompt** to guide the
  interview so even a weaker/local model runs a good intake.
- Rewire `judge` / `run_tool` to judge against the experiment document, not a thin one-file spec.

---

## Resume checklist

```bash
source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate nooa
python -m pytest tests app/tests -q          # expect all green (was 101)
python tests/run_tests.py                    # parity gate → 14 pass / 0 fail / 1 skip

# Try the MCP server with an external client:
python -m mcp_server.server                  # stdio; register via .mcp.json
# Try agent mode in the UI:
python -m app                                # tick the "agent" box, pick Claude/Ollama
```

## Key files
- Gate: `shared/pipeline.py`, `shared/harnesses/*`, `shared/execution/runner.py` (subprocess,
  shell=False), `shared/contracts_lib.py`, `shared/harness_steps.py`.
- Surfaces: `mcp_server/server.py`; `app/agent_loop.py` + `app/api/routes_chat.py` (agent branch).
- To retire (Phase B tail): `app/intent.py`, `app/resolve.py`.
- To archive (Phase A3): `langgraph_impl/`, `nooa_impl/` (still imported by the legacy
  `app/capabilities/run_pipeline.py` and `tests/run_tests.py`).
