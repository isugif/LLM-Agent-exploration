# Glossary — the vocabulary of this system

A shared vocabulary so a feature request lands in one shot. Name the **layer** you mean and the rest
follows. This doc is living — extend it as the vocabulary grows.

## The nouns

| Term | What it means here | Where it lives |
|---|---|---|
| **Intent** | Typed label for what a message wants (`run_pipeline`, `describe_workdir`). The LLM proposes it; offline it defaults to `other`. | `app/intent.py` |
| **Resolver / grounding** | Deterministic layer that corrects a weak intent and fills its slots from the message + conversation. Runs for every intent. | `app/resolve.py` |
| **Slot** | A required field an intent needs before it can act (`tool`, `file`). If unresolved, the router asks. | `resolve.REQUIRED_SLOTS` |
| **Capability** | The handler that *fulfills* one intent. | `app/capabilities/` |
| **Dispatch** | Routing a resolved intent to its capability. | `app/api/routes_chat.py` branches |
| **Probe** | Measures **facts from an input** (a file, a folder) — ground truth, not the LLM's opinion. | `shared/probes/`, `app/workdir.py:inspect` |
| **Parser** | Extracts **metrics from a tool's output** (reserved: this is *not* the message reader). | `shared/parsers/` |
| **Contract** | A tool's declared preconditions, operating range, must-not-use boundaries, and failure modes. | `bio-tools/<tool>/` |
| **Harness** | One of the four checkpoints around a run: onboarding, judgment, execution, diagnosis/evaluation. | `shared/harness_steps.py` |
| **Expectation table** | Assay-keyed expected ranges a parser's metrics get scored against. | `shared/contracts/expectations/` |
| **Panel** | The structured right-side output block, tagged by `kind` (`folder`, `catalog`, `tool`, `session`, data profile). | `app/ui/app.js` builders |
| **HRR** (human-review-required) | A gate: `HRR_` markers in a contract's machine sections block a tool from routing until a human reviews it. | contract markers, `contracts_lib.is_reviewed` |
| **Provider** | The pluggable LLM backend (Ollama / Claude / null). Deterministic code runs with it off. | `shared/llm/` |
| **Workdir** | The active working directory data paths resolve against (defaults to the launch folder). | `app/workdir.py` |

## The pipeline — say where in it you're working

```
message → Intent → Resolver (fill Slots) → dispatch → Capability
                                                         ├─ Probe   (facts from inputs)
                                                         ├─ Parser  (metrics from output)
                                                         ├─ Contract + Harnesses (run safely)
                                                         └─ returns Panel + prose
```

## A template for requesting a feature

> When a user says **\<trigger phrases\>**, classify it as intent **\<name\>**; ground it by filling
> slot **\<slot\>**; dispatch to a capability that **\<does X\>** and returns a **panel of kind
> \<kind\>**.

Drop any layer you don't care about — naming even one anchors the rest.

## Before → after

- ❌ "add a parser that gets info about the CWD folder"
  ✅ "add a **probe** that inspects the workdir, surfaced through a **describe_workdir intent** and
  its **capability**, returning a **folder panel**."
- ❌ "make it recognize when I want to set my directory"
  ✅ "add a **set_workdir intent** with a path **slot**; the **resolver** should catch 'my data is in X'."
- ❌ "check if the rustqc numbers are good"
  ✅ "add a **parser** for rustqc output and score it against an **expectation table**."

## Easily-confused pairs

- **Probe vs Parser** — a probe reads an *input* (facts before the run); a parser reads a tool's
  *output* (metrics after the run).
- **Intent vs Capability** — the intent is the *label* (what you want); the capability is the *code*
  that does it.
- **Resolver vs Intent** — classification proposes the intent; the resolver grounds it
  deterministically (corrects it, fills slots). Two separate steps on purpose.
- **Contract vs Expectation table** — the contract gates *whether* a tool may run; the expectation
  table scores *how good* its output is.
