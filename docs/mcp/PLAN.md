# Plan: MCP harness + model-driven agent loop

The durable version of the phased plan for pivoting the chat surface to a self-guarding harness the
model drives as tools. Promoted from an ephemeral planning doc so it survives a repo rename / fresh
clone. Design notes that led here: [`abundant-pondering-wave.md`](abundant-pondering-wave.md),
[`UI_chatengine.md`](UI_chatengine.md), [`UI_chatengine_discussion_summary.md`](UI_chatengine_discussion_summary.md).

## Status snapshot (2026-08-12)

- **Phase A — MCP server + self-guarding gate: DONE, merged to `main`.**
- **Phase B — model-agnostic agent loop: DONE and now the DEFAULT.** Agent drives whenever a model is
  reachable (Claude CLI preferred, else Ollama); no model → the deterministic `resolve.py` fallback.
  The LLM classifier (`app/intent.py`) is retired; `describe_data`/`session_query`/`add_tool` ported
  as agent tools; the agent path no longer imports LangGraph (`app/stage_render.py`). Orchestrators
  **kept for the comparison** (demoted in the README), not archived.
  Remaining: (a) validate loop quality with a real model on multi-step / tool-chaining tasks;
  (b) the server-side run state machine (resume + HRR pause).
- **Phase C — interactive experiment-document contract: NOT STARTED.**

Tests: 102 pass; parity gate 14/0 (deterministic).

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
- **Orchestrators.** Lifted the LangGraph node bodies into framework-neutral `shared/harnesses/*`
  (DONE — nodes now delegate). Decision: **keep** `langgraph_impl/` + `nooa_impl/` for the framework
  comparison (demoted below the chat headline in the README), NOT archived. The app/MCP use
  `shared/pipeline.py`; the trees stay runnable for the comparison + parity gate.

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

## Phase B — model-agnostic agent loop  ✅ DONE (now the default)

**Done:**
- `app/agent_loop.py` — provider-driven tool-use loop (`AgentAction` via `provider.extract`). Tools:
  read-only `list_workdir` / `list_outputs` / `read_file` / `probe_data` / `describe_data`, knowledge
  `list_catalog` / `explain_tool` / `find_tool` / `session_query` / `add_tool`, and the `run_tool`
  gate. Idempotent `run_tool` + repeat guard + deterministic close-out prevent runaway loops. No
  LangGraph import (render helpers moved to `app/stage_render.py`).
- **Default routing** (`app/api/routes_chat.py`): model reachable → agent loop (Claude CLI preferred
  via `_chat_provider`, else Ollama); no model → deterministic `resolve.py` router. The `agent` flag +
  UI checkbox are gone; the header shows the active brain.
- **Retired** the LLM classifier `app/intent.py`; moved `Intent` + `stub_text` into `app/resolve.py`,
  which stays as the deterministic offline router (its path extractors `path_in`/`aln_in`/… stay too).
- Tests: `tests/test_agent_loop.py`; app smoke routing tests (`test_chat_no_model_uses_deterministic`,
  `test_chat_model_present_uses_agent`).

**Remaining (resume here):**
1. **Validate loop quality with a real model** (Claude CLI + Ollama) across multi-step, multi-file,
   and tool-chaining tasks (e.g. align → `list_outputs` → rustqc). Tighten the system prompt if the
   model mis-picks files.
2. **Server-side run state machine** (`draft→onboarded→judged_ok→refused→running→completed`, bound to
   a server-issued run id): the framework-neutral home for resume + the HRR human-review pause — where
   "replay/restart/HITL" live now that LangGraph is out of the hot path.
3. **Provider loop tradeoff:** the subscription `claude` CLI is single-shot, so the loop is hand-rolled
   ReAct; if quality is inadequate, fall back to the Anthropic Messages API (token-billed, native
   tool-use loop). Both keep the boundary hard.

_(The earlier "archive the orchestrator trees" item is dropped — decision: keep them for the
comparison, demoted in the README.)_

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
