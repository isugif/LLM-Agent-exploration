# LangGraph vs NOOA — running comparison

Same four-harness architecture, same shared knowledge/execution layer, same Ollama model. The only
variable is the orchestration framework. This doc is filled in as the project grows; below is the
milestone-1 read.

## TL;DR (milestone 1)

Both tracks produce identical decisions on every path we tested (happy / refuse / offline). The
difference is entirely in *how you express orchestration and state*, not in what the system decides.

## 1. How you wire the flow

**LangGraph — the graph is a separate artifact.** You declare nodes and conditional edges; routing
is data you register with the graph:

```python
# langgraph_impl/graph.py
g.add_conditional_edges("judgment", _after_judgment, {"execute": "execute", END: END})
g.add_conditional_edges("execute", _after_execution, {"evaluation": "evaluation", "diagnosis": "diagnosis"})
```

**NOOA — the flow is ordinary Python.** Routing is `if` statements in a normal async function:

```python
# nooa_impl/orchestrator.py
if route.action == "refuse":
    return report
...
if not run_result.ok:
    verdict = diagnose.diagnose(run_result)
else:
    verdict = evaluate.verdict(...)
```

*Trade-off.* The graph is more work up front and adds indirection for a linear-ish flow like this
one, but it is inspectable/visualizable and forces you to name every transition. The Python
orchestrator is immediately readable and trivial to step through in a debugger, but the control
flow isn't a first-class object you can render or analyze.

## 2. Where state lives

- **LangGraph:** one explicit `PipelineState` TypedDict (`langgraph_impl/state.py`) threads through
  every node; each node returns a partial dict that LangGraph merges. State is centralized and
  serializable, at the cost of every node reading/writing a shared bag of keys.
- **NOOA:** state is local variables in the orchestrator plus fields on the agent objects
  (e.g. `self.contract`). More natural Python, but there's no single serializable state object to
  snapshot or replay for free.

## 3. How you call the LLM

- **LangGraph:** we wrote a tiny provider (`shared/llm/provider.py`) hitting Ollama's HTTP API,
  using its structured-output `format` field for typed extraction. Explicit and dependency-light.
- **NOOA:** the LLM is native. A method with a `...` body, `@strategy(PredictStrategy())`, a
  docstring (the prompt), and a pydantic return type *is* the typed extraction — no schema wiring,
  no HTTP:

```python
@strategy(PredictStrategy())
async def parse_question(self, question: str) -> DeclaredFacts:
    """Extract the platform, assay, layout, and organism the scientist states."""
    ...
```

*Trade-off.* NOOA's version is strikingly concise and keeps prompt+type+call in one place; it also
pulls in the framework's runtime (async, litellm, a metaclass that wraps methods). The LangGraph
provider is more boilerplate but you can read every byte that goes to the model.

## 4. Sharp edges hit during the build

- **NOOA requires an LLM at construction even for agents with no agentic methods** (DiagnosisAgent).
  Fix: build the client lazily and pass it to every agent; gate only the *calls* on reachability.
- **NOOA's metaclass wraps coroutine functions.** Keep deterministic helpers as `def` (sync) so
  they aren't turned into agentic methods; reserve `async` + `@strategy` for the LLM steps.
- **LangGraph** had no surprises for a flow this size; the friction is purely upfront ceremony.

## 5. "Intuitive to build with" — adding things

Because both share `shared/`, the ergonomics of *extending the knowledge* are identical and live
outside either framework:

- **Add a tool:** drop `shared/contracts/tools/<tool>.yaml` (+ a runner). No agent/graph change.
- **Add a QC check:** add a metric row to `shared/contracts/expectations/*.yaml`. No code change.
- **Add a harness step:** LangGraph = new node + edge; NOOA = new method + a line in the orchestrator.

## Open questions to revisit as the project grows

- Does LangGraph's explicit state pay off once we add retries, checkpoints, and human-in-the-loop
  interrupts (its strengths), which we haven't exercised yet?
- Does NOOA's `CodeActStrategy` (model writes Python) change the picture for the *compose* route,
  where the workflow itself is assembled rather than chosen? Not used in milestone 1.
