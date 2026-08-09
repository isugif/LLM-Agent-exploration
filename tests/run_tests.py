"""Run the declarative test cases (tests/cases.yaml) through BOTH tracks and write tests/REPORT.md.

By default this runs in DETERMINISTIC mode: it points OLLAMA_HOST at an unreachable address so both
tracks fall back to the NullProvider. That makes results stable and independent of any running model
(the LLM only adds explanations/boundary-confirmation; the pass/fail logic is deterministic). Pass
--llm to use a real Ollama and include the LLM-dependent cases (e.g. boundary-based refusal).

Exit code = number of failing (case, track) rows, so it works as a CI gate.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# --- force deterministic mode BEFORE importing anything that reads OLLAMA_HOST at import time ---
_ap = argparse.ArgumentParser(description="Run four-harness pipeline tests and write REPORT.md")
_ap.add_argument("--llm", action="store_true", help="use a real Ollama (include LLM-dependent cases)")
ARGS = _ap.parse_args()
DETERMINISTIC = not ARGS.llm
if DETERMINISTIC:
    os.environ["OLLAMA_HOST"] = "http://localhost:1"   # unreachable -> NullProvider everywhere

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared.models import RunResult  # noqa: E402
from langgraph_impl.graph import build_graph  # noqa: E402
from langgraph_impl.harnesses.diagnosis import diagnosis_node  # noqa: E402
from nooa_impl.orchestrator import run_pipeline  # noqa: E402
from nooa_impl.llm import build_llm  # noqa: E402
from nooa_impl.agents.diagnosis import DiagnosisAgent  # noqa: E402

import shutil  # noqa: E402


# out_dirs created during the run (mkdtemp per pipeline case + the multiqc input build);
# removed after REPORT.md is written so test runs don't accumulate in $TMPDIR.
TEMP_DIRS: list[str] = []


def _cleanup_temp_dirs() -> None:
    for d in TEMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


def _anyof(expected, actual) -> bool:
    return actual in expected if isinstance(expected, list) else actual == expected


def _build_multiqc_input() -> str | None:
    """Run FastQC on the good fixture into a temp dir; return it (or None if fastqc missing)."""
    if shutil.which("fastqc") is None:
        return None
    d = tempfile.mkdtemp(prefix="mqc_in_")
    TEMP_DIRS.append(d)
    import subprocess
    subprocess.run(["fastqc", "-q", "-o", d, str(REPO / "tests/inputs/good.fastq.gz")],
                   capture_output=True, timeout=300)
    return d


# --- per-track runners: return a flat dict of observed facts --------------------------------- #

def _lg_pipeline(case, fastq) -> dict:
    final = build_graph().invoke({
        "tool": case["tool"], "fastq": fastq,
        "question": case["question"], "deliverable": case.get("deliverable") or case["question"],
        "out_dir": None,
    })
    if final.get("out_dir"):
        TEMP_DIRS.append(final["out_dir"])
    return _facts(final.get("route"), final.get("run_result"), final.get("verdict"))


def _nooa_pipeline(case, fastq) -> dict:
    rep = asyncio.run(run_pipeline(
        fastq, case["question"], case.get("deliverable"), None, tool_id=case["tool"]))
    if rep.get("out_dir"):
        TEMP_DIRS.append(rep["out_dir"])
    return _facts(rep.get("route"), rep.get("run_result"), rep.get("verdict"))


def _facts(route, run_result, verdict) -> dict:
    return {
        "route": (route or {}).get("action"),
        "run_ok": (run_result or {}).get("ok") if run_result else None,
        "verdict": (verdict or {}).get("status"),
    }


def _crash_result(case) -> RunResult:
    return RunResult(tool=case["tool"], ok=False, exit_code=case.get("exit_code", 1),
                     stdout="", stderr=case.get("stderr", ""), output_dir=None,
                     audit={}, error=case.get("error"))


def _lg_crash(case) -> dict:
    v = diagnosis_node({"tool": case["tool"], "run_result": _crash_result(case).to_dict()})["verdict"]
    return _crash_facts(v)


def _nooa_crash(case) -> dict:
    llm, _, _ = build_llm()
    v = DiagnosisAgent(case["tool"], llm=llm).diagnose(_crash_result(case)).to_dict()
    return _crash_facts(v)


def _crash_facts(v: dict) -> dict:
    return {"status": v.get("status"), "has_fix": v.get("proposed_fix") is not None,
            "escalate": v.get("escalate")}


def _check(expect: dict, actual: dict):
    """Return (passed, mismatches[str])."""
    bad = []
    for key, exp in expect.items():
        if not _anyof(exp, actual.get(key)):
            bad.append(f"{key}: expected {exp}, got {actual.get(key)}")
    return (not bad), bad


def main() -> None:
    cases = yaml.safe_load((REPO / "tests/cases.yaml").read_text())["cases"]
    rows = []          # (case, track, status, expected, actual, detail)
    n_fail = 0

    mqc_input = None
    for case in cases:
        name, ctype = case["name"], case.get("type", "pipeline")

        # skips
        if case.get("requires_llm") and DETERMINISTIC:
            rows.append((name, "-", "SKIP", case["expect"], {}, "needs --llm (LLM-dependent)"))
            continue
        if case.get("requires_tool") and shutil.which(case["requires_tool"]) is None:
            rows.append((name, "-", "SKIP", case["expect"], {}, f"{case['requires_tool']} not installed"))
            continue

        fastq = case.get("fastq")
        if case.get("build_multiqc_input"):
            mqc_input = mqc_input or _build_multiqc_input()
            if mqc_input is None:
                rows.append((name, "-", "SKIP", case["expect"], {}, "fastqc needed to build input"))
                continue
            fastq = mqc_input

        for track, run in (("langgraph", _lg_pipeline if ctype == "pipeline" else _lg_crash),
                           ("nooa", _nooa_pipeline if ctype == "pipeline" else _nooa_crash)):
            try:
                actual = run(case, fastq) if ctype == "pipeline" else run(case)
                passed, bad = _check(case["expect"], actual)
            except Exception as exc:  # noqa: BLE001
                actual, passed, bad = {"error": str(exc)}, False, [f"exception: {exc}"]
            status = "PASS" if passed else "FAIL"
            n_fail += 0 if passed else 1
            rows.append((name, track, status, case["expect"], actual, "; ".join(bad)))

    _write_report(rows, n_fail)
    _cleanup_temp_dirs()
    print(f"{'DETERMINISTIC' if DETERMINISTIC else 'LLM'} mode: "
          f"{sum(1 for r in rows if r[2]=='PASS')} pass, {n_fail} fail, "
          f"{sum(1 for r in rows if r[2]=='SKIP')} skip -> tests/REPORT.md")
    sys.exit(n_fail)


def _write_report(rows, n_fail) -> None:
    import datetime
    mode = "deterministic (NullProvider)" if DETERMINISTIC else "LLM (Ollama)"
    lines = [
        "# Test report — four-harness pipeline",
        "",
        f"_Generated by `tests/run_tests.py` in **{mode}** mode on "
        f"{datetime.date.today().isoformat()}._",
        "",
        f"**{sum(1 for r in rows if r[2]=='PASS')} passed, {n_fail} failed, "
        f"{sum(1 for r in rows if r[2]=='SKIP')} skipped.**",
        "",
        "| Case | Track | Result | Expected | Actual | Notes |",
        "|------|-------|--------|----------|--------|-------|",
    ]
    for name, track, status, expected, actual, detail in rows:
        badge = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIP": "⚪ SKIP"}[status]
        lines.append(
            f"| `{name}` | {track} | {badge} | `{expected}` | `{actual}` | {detail} |")
    lines += ["", "## What each case exercises", "",
              "- **happy_fastqc / anomaly_badqual** — onboarding → judgment(run) → execute → "
              "evaluation (metrics scored vs expected ranges).",
              "- **refuse_not_fastq / refuse_empty** — judgment refuses on a blocking precondition, "
              "before any compute.",
              "- **refuse_cohort_boundary** — judgment refuses on a confirmed must-not-use boundary "
              "(needs the LLM, so skipped in deterministic mode).",
              "- **multiqc_happy** — a second tool wired in by contract + parser + probe only.",
              "- **diagnosis_oom / diagnosis_novel_escalates** — diagnosis maps a crash signal to a "
              "known fix, or escalates a novel crash.", ""]
    (REPO / "tests/REPORT.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
