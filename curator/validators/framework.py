"""Validator framework — the Python replacement for the skill's ~34 check_*.sh.

Design goals vs the bash originals:
  * one small, DOCUMENTED function per check (the bash versions were terse rg one-liners);
  * a real parse (pydantic/yaml), never indentation-regex;
  * NO hardcoded tool names (the bash checks leaked `cutadapt`, `trimmomatic`, ... into "generic"
    checkers — see check_shape_output.sh / lib_shape_common.sh);
  * a uniform typed result so the fix-loop can branch on a stable `code`.

A check takes the validated section object + a context dict and returns a CheckResult. The schema
check runs first and separately (it gates whether the object even exists). M3.1 ships the checks the
install/input/citations sections need; more are ported in M3.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ValidationError

from shared.sections.schemas import schema_for

# a CLI flag token: -o, -1, --outdir, --no-1mm-upfront. The lookbehind rejects only a preceding
# word-char or hyphen (so we don't match mid-word or the tail of "--foo"), but ALLOWS the flag to be
# preceded by a delimiter like `[ { ( | / <` — exactly how usage synopses bracket flags, e.g. `[-S <sam>]`.
_FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


def _flags(text: str) -> set[str]:
    return set(_FLAG_RE.findall(text or ""))


@dataclass
class CheckResult:
    check_id: str
    status: Literal["pass", "fail"]
    code: Optional[str]          # short fail code the fix-loop branches on, e.g. VERSION_DRIFT
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "pass"


def _ok(check_id: str) -> CheckResult:
    return CheckResult(check_id, "pass", None, "")


def _fail(check_id: str, code: str, detail: str) -> CheckResult:
    return CheckResult(check_id, "fail", code, detail)


# --------------------------------------------------------------------------- #
# Gate 0 — schema validity (turns raw dict -> typed object, or a SCHEMA_MISS)
# --------------------------------------------------------------------------- #

def check_schema(section: str, raw: dict) -> tuple[Optional[BaseModel], CheckResult]:
    """Validate raw dict against the section's pydantic schema. Returns (obj|None, result)."""
    model = schema_for(section)
    try:
        return model.model_validate(raw), _ok("schema")
    except ValidationError as exc:
        return None, _fail("schema", "SCHEMA_MISS", str(exc))


# --------------------------------------------------------------------------- #
# Section checks — (obj, ctx) -> CheckResult
# --------------------------------------------------------------------------- #

def install_methods_present(obj, ctx) -> CheckResult:
    """Every install section must offer at least one route with a non-empty command."""
    if not obj.methods:
        return _fail("install_methods_present", "EMPTY", "no install methods")
    for m in obj.methods:
        if not m.command.strip():
            return _fail("install_methods_present", "EMPTY", f"empty command for {m.manager}")
    return _ok("install_methods_present")


def install_no_code_fence(obj, ctx) -> CheckResult:
    """Clean source is fact-only: install commands must not carry markdown ``` fences (a workbook
    render artifact). Catches models that paste fenced blocks from docs."""
    for m in obj.methods:
        if "```" in m.command:
            return _fail("install_no_code_fence", "BAD_FENCE", f"fenced command for {m.manager}")
    return _ok("install_no_code_fence")


def install_version_parity(obj, ctx) -> CheckResult:
    """The version claimed by the install section must match the authoritative source version
    (ctx['source_version']) and appear in verify_expected. This is the drift catch — exactly the
    install.yml 0.11.9 vs contract 0.12.1 mismatch that motivated the redesign."""
    src = (ctx or {}).get("source_version")
    if src and obj.version != src:
        return _fail("install_version_parity", "VERSION_DRIFT",
                     f"install version {obj.version!r} != source version {src!r}")
    if obj.verify_expected and obj.version not in obj.verify_expected:
        return _fail("install_version_parity", "VERSION_DRIFT",
                     f"version {obj.version!r} not reflected in verify_expected "
                     f"{obj.verify_expected!r}")
    return _ok("install_version_parity")


def input_formats_present(obj, ctx) -> CheckResult:
    """An input section must list at least one accepted format."""
    if not obj.formats:
        return _fail("input_formats_present", "EMPTY", "no input formats listed")
    return _ok("input_formats_present")


def citations_primary_present(obj, ctx) -> CheckResult:
    """Citations must carry a primary publication with a resolvable handle (doi or url)."""
    if not obj.primary_text.strip():
        return _fail("citations_primary_present", "SRC_MISS", "missing primary citation text")
    if not (obj.doi or obj.url):
        return _fail("citations_primary_present", "SRC_MISS", "primary citation has no doi or url")
    return _ok("citations_primary_present")


def output_formats_present(obj, ctx) -> CheckResult:
    """An output section must list at least one produced artifact."""
    if not obj.formats:
        return _fail("output_formats_present", "EMPTY", "no output formats listed")
    return _ok("output_formats_present")


def usage_examples_present(obj, ctx) -> CheckResult:
    """Usage must give at least one example whose command is non-empty and unfenced."""
    if not obj.examples:
        return _fail("usage_examples_present", "EMPTY", "no usage examples")
    for e in obj.examples:
        if not e.command.strip():
            return _fail("usage_examples_present", "EMPTY", f"empty command for {e.description!r}")
        if "```" in e.command:
            return _fail("usage_examples_present", "BAD_FENCE", f"fenced command for {e.description!r}")
    return _ok("usage_examples_present")


def options_well_formed(obj, ctx) -> CheckResult:
    """Each option needs a flag and a description (an options table with blank cells is useless)."""
    if not obj.options:
        return _fail("options_well_formed", "EMPTY", "no options listed")
    for o in obj.options:
        if not o.flag.strip() or not o.description.strip():
            return _fail("options_well_formed", "EMPTY", f"incomplete option {o.flag!r}")
    return _ok("options_well_formed")


def dependencies_present(obj, ctx) -> CheckResult:
    """A dependencies section should declare at least one required OR optional dependency."""
    if not obj.required and not obj.optional:
        return _fail("dependencies_present", "EMPTY", "no required or optional dependencies")
    return _ok("dependencies_present")


def source_has_link(obj, ctx) -> CheckResult:
    """Source provenance needs at least one resolvable link (homepage/repository/docs)."""
    if not (obj.homepage or obj.repository or obj.docs):
        return _fail("source_has_link", "SRC_MISS", "no homepage/repository/docs link")
    return _ok("source_has_link")


def usage_flags_grounded(obj, ctx) -> CheckResult:
    """SOURCE-PARITY (ports the skill's R2 / "syntax = law"): every flag in a usage command must
    appear in the tool's source (ctx['source_text'], the --help). This is what catches an anchor
    leaking a fact — e.g. the fastqc `-o` idiom appearing in a hisat2 command that never had it.

    Skipped when no source is available (e.g. validating a hand-authored clean file with no --help
    at hand) — grounding is a curation-time guarantee, not a structural one.
    """
    src = (ctx or {}).get("source_text")
    if not src:
        return _ok("usage_flags_grounded")
    src_flags = _flags(src)
    for e in obj.examples:
        for f in _flags(e.command):
            if f not in src_flags:
                return _fail("usage_flags_grounded", "UNGROUNDED_FLAG",
                             f"command uses {f!r}, which is not in the tool source (anchor leak?)")
    return _ok("usage_flags_grounded")


def options_flags_grounded(obj, ctx) -> CheckResult:
    """SOURCE-PARITY for options: every documented flag must exist in the tool's source."""
    src = (ctx or {}).get("source_text")
    if not src:
        return _ok("options_flags_grounded")
    src_flags = _flags(src)
    for o in obj.options:
        for f in _flags(o.flag):
            if f not in src_flags:
                return _fail("options_flags_grounded", "UNGROUNDED_FLAG",
                             f"option {f!r} is not in the tool source")
    return _ok("options_flags_grounded")


def no_render_tokens(obj, ctx) -> CheckResult:
    """GLOBAL: the clean source must be fact-only — no Jekyll render mechanics leaked in.

    Ports the skill's BAD_TOKEN / legacy-Liquid checks, but tool-agnostic: scans the serialized
    object for `[[ ]]`, `{{ }}`, triple-backtick fences, HTML comments, or Liquid `{% %}`. These are
    a rendering concern the workbook re-applies later; they must never appear in the clean source.
    """
    import yaml as _yaml
    blob = _yaml.safe_dump(obj.model_dump(by_alias=True))
    for tok in ("[[", "]]", "{{", "}}", "```", "<!--", "{%"):
        if tok in blob:
            return _fail("no_render_tokens", "BAD_TOKEN", f"clean source contains render token {tok!r}")
    return _ok("no_render_tokens")


# runs for every section
GLOBAL_CHECKS: list[Callable[[Any, dict], CheckResult]] = [no_render_tokens]

# section -> ordered list of section-specific checks
CHECKS: dict[str, list[Callable[[Any, dict], CheckResult]]] = {
    "install": [install_methods_present, install_no_code_fence, install_version_parity],
    "input": [input_formats_present],
    "citations": [citations_primary_present],
    "output": [output_formats_present],
    "usage": [usage_examples_present, usage_flags_grounded],
    "options": [options_well_formed, options_flags_grounded],
    "dependencies": [dependencies_present],
    "source": [source_has_link],
}


def run_checks(section: str, raw: dict, ctx: Optional[dict] = None) -> list[CheckResult]:
    """Run the schema gate, then GLOBAL checks, then section-specific checks (schema first).

    If the schema gate fails, downstream checks are skipped (there's no valid object to check).
    """
    ctx = ctx or {}
    obj, schema_res = check_schema(section, raw)
    results = [schema_res]
    if obj is None:
        return results
    for check in GLOBAL_CHECKS + CHECKS.get(section, []):
        results.append(check(obj, ctx))
    return results
