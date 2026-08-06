# Adding a tool

A tool is **data + two small functions**. You do not touch the harnesses or either track.

- **Data** — one `bio-tools/<tool>/contract.yml` (the enforceable contract). This lives in the same
  folder as the tool's human-facing workbook ymls, so there is one place per tool.
- **Code** — a **parser** (turn the tool's output into a metric dict) and, only if the tool takes a
  new *input type*, a **probe** (measure facts about that input). Both are registered in
  `shared/tools/registry.py`.

Everything else — routing, refusal, diagnosis, evaluation, both the LangGraph and NOOA tracks — is
already tool-agnostic and picks the tool up from `--tool <id>`.

## Checklist

1. **`bio-tools/<tool>/contract.yml`** — fill every section (validated against
   `shared/contracts/schema/contract.schema.json`):
   - `execution.argv` — how to run it, as a **token list** (`[tool, -o, "{out_dir}", "{input}"]`).
     Placeholders `{input}`, `{out_dir}`, `{threads}` are substituted per-token; never a shell
     string, so there is no injection surface. Add `version_argv` and `install_hint`.
   - `preconditions` — assertable expressions over `measured.*` / `declared.*` facts, each `block`
     or `warn`.
   - `must_not_use` — off-label boundaries with `keywords` (cheap pre-filter; the LLM confirms).
   - `failure_modes` — a grep-able `signal` per known crash + its `fix`.
   - `operating_range`, `gotchas`, and `expectations_ref` (an assay table under
     `shared/contracts/expectations/`).

2. **Parser** in `shared/qc/<tool>_parse.py` — `parse(output_dir) -> {metric: value}`. Emit the
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

- `bio-tools/multiqc/contract.yml` — `execution.argv: [multiqc, "{input}", -o, "{out_dir}", -f]`;
  preconditions assert `measured.format == 'report_dir'` and `measured.n_reports > 0`; boundaries say
  it is not a measurement tool and not a decision-maker.
- `shared/qc/multiqc_parse.py:parse_multiqc` — reads `multiqc_data/multiqc_general_stats.txt`,
  averages metrics across samples, renames to the shared assay-table metric names.
- `shared/probes/report_dir_probe.py:probe_report_dir` — counts recognized reports in the directory.
- Both registered in `shared/tools/registry.py`.

No harness or track code changed. See `tests/REPORT.md` (`multiqc_happy`).

## Why expectations live in `shared/`, not the tool folder

An expected range like "good RNA-seq per-base quality is ≥28" is a property of the **assay**, not of
FastQC — MultiQC (or any QC tool) reuses the same table. So expectation tables live in
`shared/contracts/expectations/` and contracts reference one via `expectations_ref`. The tool folder
stays the single source of truth for everything that *is* tool-specific.
