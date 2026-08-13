# Bio Harness

**Safe agentic bioinformatics** — an LLM-agent harness that *refuses* silently-wrong analyses instead
of confidently reporting them. Machine-readable biological contracts + four checkpoints + a
server-enforced refusal gate.

## The problem

Crashes report themselves; **wrong biology does not.** A pipeline exits 0 and returns a biologically
wrong answer because an assumption was violated — in the organism, the sequencing technology, or the
software. A capable LLM agent makes this *worse*: it will always produce a plausible, well-cited
result, even when the honest answer is *"this analysis cannot support that conclusion."* That
confident-but-wrong output is the failure mode this project is built against.

## The idea

Every tool carries a **machine-readable contract** — preconditions, validated operating range,
must-not-use boundaries, known failure modes — and **four checkpoints** enforce it, each with the
right to refuse:

1. **Onboarding** — probe the actual files for *measured* facts and reconcile them against what the
   scientist *declared* (a declared-vs-measured disagreement is a first-class error signal).
2. **Judgment** — refuse a tool whose contract conflicts with the request, *before any compute*.
3. **Diagnosis** — on a crash, match it against known failure signatures.
4. **Evaluation** — on success, score output against assay-keyed expected-range tables.

Two choices make this more than four LLM vibe-checks:

- **The refusal gate is server-enforced, not requested of the model.** The harness is exposed as an
  **MCP server** whose single execution entrypoint, `run_tool`, internally runs onboarding → judgment
  → (refuse | execute) → (diagnose | evaluate) and returns the full trace — so a capable, eager agent
  **cannot skip the gate even if it never calls `judge`.** No raw shell or arbitrary-code path is ever
  exposed; the policy boundary lives in the tool surface, not in a prompt an agent can talk around.
- **The load-bearing logic is deterministic; the LLM is narrow.** Preconditions evaluate through a
  restricted AST walker (no `eval`); metric tiers and crash matching are deterministic. The model
  interprets the question and narrates — it never decides pass/fail, and the pipeline still catches
  real problems with the model switched off.

```
  you ─▶ chat (agent: claude | ollama)   ·   or an MCP client (Claude Desktop/Code)
             │  may inspect/query files + REQUEST tools — no shell is ever exposed
             ▼
        run_tool ── the ONLY execution entrypoint, server-enforced ──
             │
   onboard ─▶ judge ─▶ REFUSE  (nothing runs)
                   └─▶ run ─▶ evaluate | diagnose ─▶ full trace back to you
```

## Quick start

```bash
# create a fresh conda env and install the Python deps
conda create -n bioharness python=3.12 -y
conda activate bioharness
pip install -r requirements.txt          # fastapi + uvicorn + mcp[cli] + langgraph + pydantic + …
conda install -c bioconda fastqc -y      # FastQC 0.12.x (the first wired tool)
bash shared/data/fetch_virus_fastq.sh    # a small SARS-CoV-2 test FASTQ

python -m app                            # http://127.0.0.1:8000  — the chat opens here
```

`python -m app` drops you into a chat. With a model reachable it uses the **agent** — the local
`claude` CLI (your subscription, no API key) if installed, else Ollama — which drives the harness as
tools; only `run_tool` executes anything. With **no** model it falls back to a deterministic router, so
it still works offline. Try:

- *"run fastqc on `shared/data/SRR11140744_10k.fastq.gz`"* → watch it onboard → judge → run → evaluate.
- *"assess these reads and give me the overall cohort quality conclusion"* → watch it **refuse before
  compute** (FastQC is not a cohort-QC tool — a must-not-use boundary).

External clients (Claude Desktop/Code) can drive the same harness over stdio:
`python -m mcp_server.server`. (The NOOA research track needs one extra, non-PyPI dependency — see
[`docs/DEVELOPING.md`](docs/DEVELOPING.md).)

### Local models (Ollama)

The agent needs a capable **text** model with good structured-output / tool selection (avoid vision
models for the tool loop). Default: `qwen3.6:35b-a3b` — a fast mixture-of-experts model. Pull it and
keep it warm so it isn't reloaded between calls:

```bash
ollama pull qwen3.6:35b-a3b               # or set your own with the header's model dropdown / OLLAMA_MODEL
export OLLAMA_KEEP_ALIVE=-1               # keep the model resident (or e.g. 30m); read by `ollama serve`
ollama serve                             # start the server in that same environment
```

`OLLAMA_KEEP_ALIVE` is an **Ollama server** setting — export it in the shell (or your launchd/systemd
unit) where `ollama serve` runs; `-1` pins the model in memory, avoiding the multi-second reload that
otherwise hits the first call after a few idle minutes.

## Status — early, and honest about it

FastQC and MultiQC are the first two tools; the durable contribution is the **pattern** — machine-
readable biological contracts + a server-enforced refusal gate — not the tool count. The **benchmark
is the deliverable in progress**: a committed suite ([`tests/REPORT.md`](tests/REPORT.md)) already
scores each failure mode as a fixture (happy path, precondition refusal, must-not-use refusal,
anomaly, known-crash diagnosis, novel-crash escalation); next is adversarial cases, null-model
controls, and per-checkpoint precision/recall on whether each check catches what it claims to.

## More

- **Architecture + the trust boundary** — [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Developing** — repo layout, adding a tool, the curator, the LangGraph↔NOOA comparison, and tests:
  [`docs/DEVELOPING.md`](docs/DEVELOPING.md)
- **Built two ways** (LangGraph + NOOA) on one shared core, for an honest framework comparison —
  [`docs/COMPARISON.md`](docs/COMPARISON.md)
- **Design notes** (the MCP pivot + the trust-boundary discussion) — [`docs/mcp/PLAN.md`](docs/mcp/PLAN.md)

## License

MIT — see [`LICENSE`](LICENSE).
