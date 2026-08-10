# Adding a tool

A tool is **data + two small functions**. You do not touch the harnesses or either track.

- **Data** — a `bio-tools/<tool>/manifest.yml` plus `clean/<section>.yml` files. There is **no**
  single `contract.yml`: the runtime contract is *assembled* at load time by
  `shared/contracts_lib.py:load_contract` from the sections the manifest marks `machine: true`
  (`meta`, `execution`, `preconditions`, `must_not_use`, `failure_modes`). Context sections
  (`install`, `usage`, `input`, …) load situationally. One folder per tool is its single source of
  truth. Each section validates against a **pydantic** schema in `shared/sections/schemas.py`.
- **Code** — a **parser** (turn the tool's output into a metric dict) and, only if the tool takes a
  new *input type*, a **probe** (measure facts about that input). Both are registered in
  `shared/tools/registry.py`.

Everything else — routing, refusal, diagnosis, evaluation, both the LangGraph and NOOA tracks — is
already tool-agnostic and picks the tool up from `--tool <id>`.

## Fastest start — auto-curate the fact sections

The **curator** provisions the tool (bioconda) and writes the CONTEXT (fact) sections + a manifest,
then scaffolds the enforceable MACHINE sections as `HRR_` placeholders for you to fill:

```bash
python -m curator.run --tool star                       # installs `star`, auto-resolves binary STAR
python -m curator.run --tool star --url <repo> --full   # add a doc source; curate all fact sections
```

It handles package/binary name mismatches automatically (bioconda `star` → binary `STAR`); override
with `--binary`. Output lands in `bio-tools/<tool>/` (`manifest.yml`, `clean/*.yml`). The harness
**refuses to route the tool** until you replace the `HRR_` markers in
`clean/{preconditions,must_not_use,failure_modes,meta,execution}.yml`, then add the parser below.

## Checklist

1. **`bio-tools/<tool>/manifest.yml` + the machine sections under `clean/`** — each validates
   against its pydantic schema in `shared/sections/schemas.py`:
   - `clean/meta.yml` — `summary` (used by the judgment prompt), `expectations_ref` (an assay table
     under `shared/contracts/expectations/`), and `category_tags` (purpose labels from
     `shared/knowledge/categories.py`, which power `find_tool`).
   - `clean/execution.yml` — `argv` as a **token list** (`[tool, -o, "{out_dir}", "{input}"]`).
     Placeholders `{input}`, `{out_dir}`, `{threads}` are substituted per-token; never a shell
     string, so there is no injection surface. Add `version_argv` and `install_hint`.
   - `clean/preconditions.yml` — assertable expressions over `measured.*` / `declared.*` facts, each
     `block` or `warn`.
   - `clean/must_not_use.yml` — off-label boundaries with `keywords` (cheap pre-filter; the LLM confirms).
   - `clean/failure_modes.yml` — a grep-able `signal` per known crash + its `fix`.
   - `manifest.yml` lists every section (`name`, `path`, `machine`, `load_when`) and any `runtimes:`
     traits to compose (e.g. `[java]` inherits the OOM→`-Xmx` failure mode). The `machine: true`
     sections are what `load_contract` assembles; until their `HRR_` placeholders are replaced, the
     judgment harness **refuses to route the tool**.

2. **Parser** in `shared/parsers/<tool>_parse.py` — `parse(output_dir) -> {metric: value}`. Emit the
   metric names your `expectations_ref` table scores (metrics not in the table are ignored; missing
   metrics are simply not scored). Register it in `shared/tools/registry.py:PARSERS`.

3. **Probe (only if new input type)** — if the tool consumes something other than a FASTQ (e.g. a
   directory of reports), add `shared/probes/<type>_probe.py` returning measured facts whose keys
   match your contract's preconditions, and register it in `shared/tools/registry.py:PROBES`.
   Reusing an existing input type? Skip this — the default FASTQ probe is used.

4. **Run it:**
   ```bash
   python -m langgraph_impl.run --tool <id> --fastq <input> --question "..."
   python -m nooa_impl.run      --tool <id> --fastq <input> --question "..."
   ```

5. **(Optional) add a test case** in `tests/cases.yaml` and rerun `python tests/run_tests.py`.

## Worked example — MultiQC (already in the repo)

MultiQC aggregates a *directory* of other tools' reports, so it needed the new-input-type path:

- `bio-tools/multiqc/manifest.yml` + `clean/` — `execution.argv: [multiqc, "{input}", -o, "{out_dir}", -f]`;
  `preconditions` assert `measured.format == 'report_dir'` and `measured.n_reports > 0`; `must_not_use`
  says it is not a measurement tool and not a decision-maker.
- `shared/parsers/multiqc_parse.py:parse_multiqc` — reads `multiqc_data/multiqc_general_stats.txt`,
  averages metrics across samples, renames to the shared assay-table metric names.
- `shared/probes/report_dir_probe.py:probe_report_dir` — counts recognized reports in the directory.
- Both registered in `shared/tools/registry.py`.

No harness or track code changed. See `tests/REPORT.md` (`multiqc_happy`).

## Why expectations live in `shared/`, not the tool folder

An expected range like "good RNA-seq per-base quality is ≥28" is a property of the **assay**, not of
FastQC — MultiQC (or any QC tool) reuses the same table. So expectation tables live in
`shared/contracts/expectations/` and contracts reference one via `expectations_ref`. The tool folder
stays the single source of truth for everything that *is* tool-specific.
