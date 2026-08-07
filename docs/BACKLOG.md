# Backlog

Enhancements we've identified but deferred. Not a commitment or an ordering — a place to park ideas
so they aren't lost. Add items as they come up; move to a milestone when we pick one up.

Status: 💡 idea · 📋 scoped · 🔨 in progress · ✅ done (link the commit/PR)

---

## Judgment "retrieve & match" — automatic tool selection

**Status:** 💡 idea

**What:** Today the tool is named explicitly (`--tool fastqc`). This item makes the judgment harness
*choose* the tool: parse the spec (organism, assay, data type, goal), retrieve candidate tool
contracts from the library, and rank them by fit — rejecting any whose contracts conflict with the
spec (the fit critic's real job). Emits a decision + rationale + confidence, and may route to
**reuse** (a validated pipeline covers it), **adapt** (swap a better-fit component), or **compose**
(assemble a novel arrangement).

**Why it matters:** it's the core agentic upgrade — moving from "run the tool I was told to" to
"decide the right tool up front." The pluggable contract library built in milestone 2 is exactly the
substrate this needs.

**Rough shape:** a retrieval step over `bio-tools/*/contract.yml` + a ranking/critic step
(deterministic contract checks first, LLM for tie-breaks). Structural ceiling: it can only reject
what a contract already declares — so it grows with the contract library.

---

<!-- Template for new items:

## <short title>

**Status:** 💡 idea

**What:** ...

**Why it matters:** ...

**Rough shape:** ...

-->
