# Design principles

Cross-cutting rules for the whole system (not any one harness). Several were learned the hard way by
rewriting the `section-yml-curator` skill (designed by Alex Badaczewska-Dawid, [@aedawid](https://github.com/aedawid)) —
it broke wherever knowledge/logic was **duplicated and implicit**, and worked wherever it was **data,
typed, and single-source**.

## The meta-principle

> **Push knowledge into typed, single-source *data*; keep *code* generic; keep the *LLM* narrow.**

Contracts, expectation tables, and traits are data. The harness code is tool-agnostic. The LLM is used
only at narrow judgment points and never decides pass/fail. Everything below is a corollary.

## 1. The authority hierarchy (resolve conflicts explicitly)

The core defense against *silent wrong answers* is that when two signals disagree, **a documented
precedence decides — never the more convenient or more confident one.** The skill encoded this as a
priority lattice (`TOOL_BEHAVIOR > SOURCE > SYNTAX > PATTERN > DEMO`). Ours:

| When these conflict | This wins | Because | Applied in |
|---|---|---|---|
| **Measured** vs **Declared** facts | **Measured** | probing the file is ground truth; the user can be wrong | onboarding (`Spec.disagreements`) |
| **Deterministic check** vs **LLM opinion** | **Deterministic** | a metric tier / precondition assert is auditable; the LLM only *explains* | judgment preconditions, evaluation tiers |
| **Source** vs **Anchor/Pattern** | **Source** | facts come from `--help`/docs/measured data, never a template/example (DB3) | curator (grounding/generalize) — but a general rule |
| **Tool-specific** vs **inherited trait** | **Tool-specific** | a tool's own contract overrides a shared default | `contracts_lib._merge_failure_modes` |
| **Human-reviewed** vs **auto-generated** | **Human-reviewed** | the enforceable contract is expert judgment, not doc-scraping | HRR gate (`is_reviewed`) |
| **Contract violation** vs **"but it runs"** | **Refuse** | running-but-wrong is the failure mode we exist to prevent | judgment `must_not_use` / preconditions |

**Global rule: `REFUSE > GUESS`.** Every harness has the right to refuse — `judgment→refuse`,
`evaluation→cannot_assess`, `provision→blocked_install`, HRR pending-review. A confident wrong answer
is worse than "I can't assess this."

When a *new* conflict appears in the design, add a row here first, then implement it — don't resolve it
implicitly in code.

## 2. Single source of truth; make parity a gate, not an afterthought

Every fact/logic should live in exactly one place. Where redundancy is *unavoidable* (the two framework
tracks; the clean source vs the render-only workbook), the parity check is **first-class**, not a
drift-policer bolted on later (the skill needed `check_contract_consistency.sh` reactively). Examples we
should enforce as gates: both tracks agree on the same input; every `runtimes:`/`expectations_ref`
resolves; every manifest section file exists. (See BACKLOG "proactive parity gates".)

## 3. Deterministic tools return typed facts — never "next-step instructions"

Keep the deterministic/LLM boundary clean. Deterministic code returns typed results (`RunResult`,
`CheckResult`, `RouteDecision`, `InstallOutcome`); the orchestration decides what happens next; the LLM
does narrow judgment. Do **not** let a tool's stdout become control flow (the skill's validator scripts
`echo`-ed the agent's next cognitive step — that's how prose and code drift apart).

## 4. Stable, typed error codes (toward an incident library)

Failures and refusals carry **stable short codes** (`SRC_MISS`, `UNGROUNDED_FLAG`, `VERSION_DRIFT`,
`blocked_install`, HRR, `failure_modes` ids). Stable codes are what make the fix-loop, the diagnosis
harness, and the premise's *incident library* (match known → propose fix; escalate novel → human
curation) possible. A unified taxonomy across harnesses is the next step. (See BACKLOG.)

## 5. Test the deterministic extraction layer — that's where silent bugs hide

The parsers/validators that turn tool output into facts are the highest-risk surface: a mis-parsed
metric silently flips a verdict — exactly the failure this project targets. Rewriting the skill's
checks (and building the curator's grounding/version parsing) surfaced multiple *self-inflicted* regex
bugs. Treat `shared/parsers/*` and the validators as needing **golden-file tests**, not trust. (See
BACKLOG.)

## 6. Enforceable knowledge is versioned and human-curated

The enforceable contract (preconditions/must_not_use/failure_modes) and the reusable traits are expert
judgment: authored/reviewed by a human, marked HRR until vetted, versioned, and **write-once-reused**
via composition. Auto-generation is for *facts* (the curator), never for judgment.

---

*Add to this file when a new cross-cutting rule emerges — especially a new row in the authority table.*
