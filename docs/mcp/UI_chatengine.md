# UI / Chat Engine — keeping Claude/Codex inside the harness

## Goal

Keep the current UI, but replace the brittle intent-router brain with Claude/Codex as the chat layer while preserving the bioinformatics harness as the only trusted execution path.

The core requirement is simple:

- the model may **chat, ask follow-ups, and request tools**
- the server must be the **only place that can execute tools**
- every run must pass through the harness: **onboard → judge → run/refuse → evaluate/diagnose**

## The key risk

If Claude/Codex can execute commands directly, it can bypass the harness.

That breaks the whole design.

So the real boundary is not “UI vs MCP” — it is:

> **No raw execution primitive is exposed to the model.**

## Recommended shape

Keep the UI as the client, but make it a thin client.

### UI
- chat input
- session state
- workdir display
- facts / plots / report panels
- stream of harness stages and refusal reasons

### Server
- the only place that can actually run tools
- owns the MCP surface
- owns the execution gate
- enforces onboarding and judgment before execution

### Claude/Codex
- reasoning layer
- chat onboarding
- clarification
- tool selection request
- narration of results

## What the model may do

The model can:

- interpret user intent
- ask clarifying questions
- call read-only tools
- propose a tool to run
- request `run_tool(...)`

The model must not:

- call shell directly
- invoke arbitrary code
- bypass onboarding
- bypass judgment
- jump straight to execution

## How routing is enforced

Routing must be **server-enforced**, not client-enforced.

### Required pattern

```text
model chat → server receives request → onboard → judge → run/refuse → evaluate/diagnose
```

### Forbidden pattern

```text
model chat → model chooses tool → direct shell/exec
```

## Safe MCP surface

Expose only narrow, trusted tools:

- `probe_data`
- `list_catalog`
- `explain_tool`
- `onboard_experiment`
- `judge`
- `run_tool`
- `evaluate_output`
- `diagnose_failure`

Do **not** expose:

- generic shell execution
- arbitrary Python execution
- file write primitives outside the harness
- “just run this command” escape hatches

## The execution rule

`run_tool(...)` must be self-guarding.

It should internally do:

1. onboarding
2. judgment
3. refusal or execution
4. diagnosis/evaluation

That means the client never decides that a run is allowed.  
The server decides.

## State machine idea

A simple server-side state machine makes routing enforceable:

- `draft`
- `onboarded`
- `judged_ok`
- `refused`
- `running`
- `completed`

Reject any request that tries to skip a step.

Bind later steps to a server-issued run id so stale or mismatched requests cannot jump ahead.

## What this means for the current UI

The current UI can stay.

But its role changes:

- **before:** UI + hand-built intent/router
- **after:** UI + Claude/Codex chat brain + trusted MCP server

That gives:

- better conversational UX
- less brittle intent parsing
- preserved harness guarantees
- no direct execution bypass

## Best control posture

If control matters most:

- keep the UI
- make it a thin MCP client
- keep execution entirely on the server
- let the model reason, but never let it execute directly

## Practical summary

The clean architecture is:

- **UI = client and display**
- **Claude/Codex = conversational reasoning**
- **MCP server = trusted enforcement boundary**
- **harness = the only allowed execution path**

That preserves the current project’s safety model while removing the clunky chat routing layer.

