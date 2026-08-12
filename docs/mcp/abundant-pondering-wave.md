# Design notes — pivot the chat surface to an MCP server (DISCUSSION, not yet decided)

> Saved so we can resume after a reboot. This is a strategic design discussion, not an approved
> implementation plan. Repo: `/Users/andrewseverin/AI/exploration/LLM-Agent-exploration`.
> When we're ready, promote the decided parts into `docs/` (e.g. `docs/MCP-PIVOT.md`) + BACKLOG.

## The problem that started this

The hand-rolled chat interface feels clunky — it needs near-exact phrases to get intent across.
That layer (`app/intent.py` + `app/resolve.py`) is a hand-built NLU/router we wrote to compensate
for a weak local model. We've spent much of this session patching it (the "run multiqc" misroute,
the workdir phrases, dir-vs-file slot filling). It's a treadmill: Claude already does intent,
slot-filling, follow-ups, clarification, multi-file, and memory natively.

## The thesis (agreed)

- **The clunky part is disposable.** `app/intent.py` + `app/resolve.py` re-implement what a capable
  agent does for free.
- **The moat is the four checkpoints + contract×trait knowledge + probes.** Already cleanly isolated:
  `shared/harness_steps.py` (pure functions), `shared/contracts_lib.py` (eval/scoring), the probes
  (`shared/probes/*`), the runner (`shared/execution/runner.py`); `app/capabilities/*` are thin
  (run_pipeline is 88 lines). So this is a **re-exposure, not a rewrite**.
- **MCP is the right shape.** Expose the moat as MCP tools + resources; let the client (Claude
  Desktop / Claude Code, or later a local-model agent loop) supply the intelligence. Kills the
  exact-phrase problem, premium UX with ~zero UI work.

## The MCP server design (sketch)

**Tools (verbs), ~one per harness + support:**
- `probe_data(path)` — measured facts (dispatch fastq / aln / report_dir probe by content). The
  "gather better metadata" piece.
- `onboard_experiment(question, files[, declared])` — build/validate the experiment-document
  contract: reconcile declared-vs-measured, return the spec + disagreements.
- `judge(tool, spec)` — the fit critic: run|refuse + reasons (preconditions, boundaries, HRR gate).
- `run_tool(tool, inputs)` — contract-driven execution.
- `evaluate_output(tool, out_dir)` / `diagnose_failure(...)` — score metrics vs expectation tables /
  match failure modes.
- `find_tool` / `explain_tool` / `list_catalog` — contract knowledge (reuse `app/capabilities/*`).
- (optional) `add_tool` — curator provisioning (HRR-gated).

**Resources (nouns, read-only context the agent can pull):**
`contract://<tool>`, `trait://<name>`, `expectations://<assay>`, `catalog://`, maybe
`session://<sid>/runs`.

**THE HARD RULE (make-or-break):** the refusal gate must be **server-enforced, not advisory**.
`run_tool` must itself run onboarding→judgment and refuse — never trust the agent called `judge`
first. A capable, eager agent will otherwise skip the gate and the whole silent-failure thesis
evaporates. So `run_tool` internally = onboard → judge → (refuse|execute) → (diagnose|evaluate) and
returns the full trace; `judge`/`probe`/`evaluate` stay separate for transparency. Stronger than
today (where the graph guarantees order).

## The onboarding upgrade (the best part — user's idea)

"Reconfigure onboarding to create a better experiment-document contract." Today onboarding is one
question + one file → a thin spec. Reimagined: an **interactive experiment-design contract**. Claude
interviews the scientist, calls `probe_data` per file, and `onboard_experiment` reconciles
declared-vs-measured and returns disagreements ("you said 3 replicates but I see 6 files with 2
sample aliases"; "you said paired-end, these look single-end"). That's "catch human mistakes before
executing," and it fits the existing versioned-contract philosophy. Reuse `shared/harness_steps.py:
reconcile`.

## Honest trades

- **Offline UX regresses.** The deterministic core stays offline (probes/judgment need no LLM), but
  the *great* chat experience now depends on a capable client. Local-via-MCP-agent is real but won't
  match Claude.
- **Branded panels/plots** (facts tables, quality charts, Report tab) don't come along for free if we
  drive from Claude instead of the custom app — TBD whether that matters.
- **Subsumes BACKLOG #4** (function-calling intent router) — MCP is the bigger, better version.

## Framework comparison (LangGraph vs NOOA) gets reframed — a real decision

MCP splits the two jobs "the framework" currently fuses: (1) tool interface → the MCP server
(framework-neutral); (2) orchestration / agentic dynamism → the client. The current comparison is
inconclusive **by construction** (`docs/COMPARISON.md` §8–9: "thin wrappers, no decisive winner") —
the four-harness flow is linear + deterministic, the one control-flow shape where frameworks add
nothing. Frameworks actually diverge on agent-loop concerns (dynamic tool selection, HITL interrupts
+ checkpointing = LangGraph; CodeAct/compose = NOOA), which in an MCP world live in the client.

Three futures for `langgraph_impl/` + `nooa_impl/`:
- **Reading 1 — MCP supersedes it.** Claude is the client → Claude's loop orchestrates, neither
  framework is in the hot path. Keep `shared/` + MCP server; the two `*_impl/` trees become
  historical. Comparison is *answered*: "a frontier client beats either wrapper."
- **Reading 2 — they become two MCP *clients*.** Rewrite each track as an agent that drives the MCP
  server (the local/offline path). Comparison now on interrupts/checkpointing/compose/fan-out — where
  they actually differ. Cleaner, fairer version of the two BACKLOG experiments ("LangGraph HITL
  checkpoint", "NOOA CodeAct compose").
- **Reading 3 — both, split by client.** One server. Claude = premium client (no framework). Local
  path = one MCP-client agent, and *that's* where the LangGraph-vs-NOOA (or the **hybrid**) bake-off
  happens.

The BACKLOG "hybrid" item gets crisper as an MCP client: LangGraph owns the conversation +
checkpoint + human-review pause; MCP tools are what it calls. "Human-curation loop as first hybrid"
maps exactly: server surfaces an HRR refusal → LangGraph client `interrupt()` → human reviews the
contract → resume. MCP *is* the seam, removing the awkward seam-discipline worry.

## Open decisions (to resolve on resume)

1. **Client/app strategy:** (a) server + drive with Claude, retire intent/resolve brain
   [recommended]; (b) server + keep the app, swap its brain to tool-calls; (c) server as an add-on,
   app untouched for now.
2. **Start scope:** (a) read-only spike — minimal stdio MCP server with `probe_data` + `catalog` +
   `explain_tool`, point Claude at it, prove the loop [recommended]; (b) spike + the gate
   (`onboard_experiment`, `judge`, self-guarding `run_tool`, evaluate/diagnose); (c) full server +
   experiment-document upgrade.
3. **Local model:** (a) Claude-first, local later [recommended]; (b) local stays co-equal (shapes
   tool design toward smaller-model-friendly outputs); (c) drop local for now.
4. **Framework comparison:** retire (Reading 1), relocate to the client layer (Reading 2/3), or keep
   as-is for now.
5. **Audience:** just you/your lab, or eventually bench scientists? (raises the value of the guided
   experiment-document interview).

## Where we left off

Mid-discussion, still clarifying before shaping the plan. User asked to expand on the framework-
comparison reframing (done, above) and then to save state before a reboot. **Next step on resume:**
work through the open decisions (start with #1 and #2), then write the actual phased implementation
plan.

## Suggested phasing (once decided)

- **Phase 0 (spike):** minimal stdio MCP server, read-only tools (`probe_data`, `list_catalog`,
  `explain_tool`); point Claude Code/Desktop at it; prove the loop. Small.
- **Phase 1 (the gate):** `onboard_experiment`, `judge`, self-guarding `run_tool`,
  `evaluate_output`/`diagnose_failure`. Wrap `shared/` + reuse `app/capabilities/*`. Core value.
- **Phase 2 (resources):** expose `contract://`, `trait://`, `expectations://`, `catalog://`.
- **Phase 3 (experiment document):** interactive experiment-document onboarding (schema +
  reconciliation + persistence + an MCP prompt to guide the interview).
- **Phase 4 (clients):** decide the app's fate (retrofit as MCP client) and/or a local-model MCP
  agent loop; if Reading 2/3, this is where the framework bake-off lives.

## Key files (for whoever implements)

- Reusable core: `shared/harness_steps.py`, `shared/contracts_lib.py`, `shared/execution/runner.py`,
  `shared/probes/{fastq_probe,aln_probe,report_dir_probe}.py`, `shared/tools/registry.py`,
  `shared/catalog.py`.
- Thin capabilities to reuse: `app/capabilities/{describe_data,run_pipeline,explain_tool,find_tool,
  session_query,add_tool}.py`.
- The disposable brain: `app/intent.py`, `app/resolve.py`.
- Orchestrators (fate TBD): `langgraph_impl/graph.py`, `nooa_impl/orchestrator.py`.
- Context: `docs/COMPARISON.md` §8–9, `docs/BACKLOG.md` ("hybrid", "stress-test framework edges",
  item #4 function-calling router), `docs/ARCHITECTURE.md`, `docs/PRINCIPLES.md`.
- No MCP dependency in the repo yet (`requirements.txt` has none) — greenfield.
