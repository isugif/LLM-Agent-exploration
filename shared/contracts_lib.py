"""Load and reason over component contracts.

This is the enforcement engine both tracks share. It does four things:

  1. load_contract / validate_contract  -> ASSEMBLE the runtime contract from a tool's clean machine
     sections (per bio-tools/<tool>/manifest.yml) + validate each section against its pydantic schema.
  2. evaluate_preconditions             -> run each `assert` against declared/measured facts.
  3. match_boundaries                    -> cheap keyword pre-filter of must_not_use vs a deliverable.
  4. score_metric / load_expectations    -> tier a measured metric against the expected-range table.

The contract is no longer a single `contract.yml`; it is assembled from the `machine: true` sections
listed in the tool's manifest (execution, preconditions, must_not_use, failure_modes, meta). Those
clean per-section ymls are the single source of truth; the harness sees the same dict shape as before.

The `assert` strings are evaluated with a *restricted* AST walker (see safe_eval), NOT python
`eval`. Only comparisons, boolean ops, literals and attribute access on the fact namespaces
(`declared`, `measured`) are allowed. Anything else raises. This keeps contract authoring
declarative and safe even though contracts are data, not code.
"""

from __future__ import annotations

import ast
import operator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parent.parent
# Per-tool contracts live in the tool's own folder — the single source of truth, alongside the
# human-facing workbook ymls. Expectation tables live in shared/ because they are a property of the
# ASSAY (e.g. "good RNA-seq quality is >=28"), not of any one tool, and are reused across tools.
TOOLS_ROOT = REPO_ROOT / "bio-tools"
CONTRACTS_ROOT = Path(__file__).parent / "contracts"
SCHEMA_PATH = CONTRACTS_ROOT / "schema" / "contract.schema.json"
EXPECTATIONS_ROOT = CONTRACTS_ROOT / "expectations"
# Reusable traits (three pillars): runtime (software), biology, domain. Written once, composed by many.
TRAITS_ROOT = Path(__file__).parent / "traits"


# --------------------------------------------------------------------------- #
# Loading & schema validation
# --------------------------------------------------------------------------- #

def load_manifest(tool_id: str) -> dict[str, Any]:
    with open(TOOLS_ROOT / tool_id / "manifest.yml") as fh:
        return yaml.safe_load(fh)


def load_section(tool_id: str, rel_path: str) -> Any:
    """Load one raw section yml (relative to the tool folder). Used for situational loading too —
    e.g. open the `install` section only on an install error."""
    with open(TOOLS_ROOT / tool_id / rel_path) as fh:
        return yaml.safe_load(fh)


def section_path(tool_id: str, section_name: str) -> str | None:
    """Return the manifest path for a named section (any section, machine or context), or None."""
    for ref in load_manifest(tool_id).get("sections", []):
        if ref["name"] == section_name:
            return ref["path"]
    return None


def load_trait(kind: str, name: str) -> dict[str, Any]:
    """Load + validate a reusable trait (shared/traits/<kind>/<name>.yml) against the Trait schema."""
    from shared.sections.schemas import Trait

    with open(TRAITS_ROOT / kind / f"{name}.yml") as fh:
        data = yaml.safe_load(fh)
    Trait.model_validate(data)                    # raises on malformed trait
    return data


def list_traits(kind: str) -> list[str]:
    d = TRAITS_ROOT / kind
    return sorted(p.stem for p in d.glob("*.yml")) if d.exists() else []


def _merge_failure_modes(base: list[dict], extra: list[dict]) -> list[dict]:
    """Append `extra` failure_modes to `base`, deduped by id — base (tool-specific) wins."""
    seen = {fm["id"] for fm in base}
    return base + [fm for fm in extra if fm["id"] not in seen]


def load_contract(tool_id: str) -> dict[str, Any]:
    """Assemble the runtime contract dict from the tool's `machine: true` sections, then COMPOSE any
    declared runtime traits (manifest `runtimes:`) into it.

    Produces the same keys the harness already consumes: id, version, summary, expectations_ref,
    execution, preconditions, must_not_use, failure_modes. `meta` merges (summary, expectations_ref);
    the other machine sections map to a same-named key. Runtime traits contribute `failure_modes`
    (e.g. any Java tool inherits the OOM→-Xmx fix) — deduped by id, tool-specific entries winning.
    """
    manifest = load_manifest(tool_id)
    contract: dict[str, Any] = {"id": manifest["tool"], "version": manifest.get("version")}
    for ref in manifest.get("sections", []):
        if not ref.get("machine"):
            continue
        data = load_section(tool_id, ref["path"])
        name = ref["name"]
        if name == "meta":
            contract.update(data or {})          # summary, expectations_ref
        else:
            contract[name] = data                 # execution / preconditions / must_not_use / failure_modes

    # compose runtime traits (software pillar): inherit their failure_modes
    for rt in manifest.get("runtimes", []):
        trait = load_trait("runtime", rt)
        if trait.get("failure_modes"):
            contract["failure_modes"] = _merge_failure_modes(
                contract.get("failure_modes", []), trait["failure_modes"])
    return contract


def find_hrr_markers(node: Any) -> list[str]:
    """Recursively collect any HRR_ ('human review required') markers in a contract's values.

    A scaffolded-but-unreviewed machine section carries HRR_ placeholders; their presence means the
    tool's enforceable contract hasn't been vetted by a human yet.
    """
    from shared.sections.scaffold import HRR

    found: list[str] = []
    if isinstance(node, str):
        if HRR in node:
            found.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            found.extend(find_hrr_markers(v))
    elif isinstance(node, (list, tuple)):
        for v in node:
            found.extend(find_hrr_markers(v))
    return found


def is_reviewed(contract: dict[str, Any]) -> bool:
    """True iff the assembled contract has no HRR_ markers (i.e. a human has vetted it)."""
    return not find_hrr_markers(contract)


def validate_contract(contract: dict[str, Any]) -> None:
    """Validate the assembled contract's machine sections against their pydantic schemas.

    Replaces the old JSON-schema check on a monolithic contract.yml. Raises pydantic ValidationError
    (or ValueError for a missing required key) if any section is malformed.
    """
    from shared.sections.schemas import (
        ExecutionSection, LIST_SECTION_ITEM, MetaSection,
    )

    MetaSection.model_validate({"summary": contract.get("summary", ""),
                                "expectations_ref": contract.get("expectations_ref")})
    ExecutionSection.model_validate(contract.get("execution") or {})
    for key, item_model in LIST_SECTION_ITEM.items():
        for item in contract.get(key, []):
            item_model.model_validate(item)


def load_expectations(contract: dict[str, Any]) -> dict[str, Any]:
    ref = contract.get("expectations_ref")
    if not ref:
        return {}
    with open(EXPECTATIONS_ROOT / ref) as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------- #
# Restricted expression evaluation for preconditions
# --------------------------------------------------------------------------- #

_ALLOWED_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


def safe_eval(expr: str, namespaces: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a restricted boolean expression like `measured.n_reads > 0`.

    Allowed: comparisons, and/or/not, literals, names bound in `namespaces`, and
    single-level attribute access (`measured.n_reads`) which reads dict keys.
    """
    tree = ast.parse(expr, mode="eval").body

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.BoolOp):
            vals = [_eval(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not _eval(node.operand)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comp in zip(node.ops, node.comparators):
                fn = _ALLOWED_CMP.get(type(op))
                if fn is None:
                    raise ValueError(f"comparator not allowed: {type(op).__name__}")
                if not fn(left, _eval(comp)):
                    return False
                left = _eval(comp)
            return True
        if isinstance(node, ast.Attribute):     # measured.n_reads -> namespaces['measured']['n_reads']
            base = node.value
            if not isinstance(base, ast.Name) or base.id not in namespaces:
                raise ValueError(f"attribute access only on fact namespaces, got: {ast.dump(node)}")
            return namespaces[base.id].get(node.attr)
        if isinstance(node, ast.Name):
            if node.id in namespaces:
                return namespaces[node.id]
            raise ValueError(f"name not allowed: {node.id}")
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [_eval(e) for e in node.elts]
        raise ValueError(f"expression element not allowed: {type(node).__name__}")

    return bool(_eval(tree))


def evaluate_preconditions(
    contract: dict[str, Any], declared: dict[str, Any], measured: dict[str, Any]
) -> tuple[list[dict], list[dict]]:
    """Return (blocking_failures, warnings). Each item: {id, message, severity, assert}.

    A precondition whose expression can't be evaluated (e.g. missing fact) is treated as a
    warning, not a silent pass — an un-checkable assumption is itself a risk.
    """
    ns = {"declared": declared, "measured": measured}
    blocking, warnings = [], []
    for pc in contract.get("preconditions", []):
        try:
            passed = safe_eval(pc["assert"], ns)
        except Exception as exc:  # noqa: BLE001 - surface as warning, never crash the run
            warnings.append({**pc, "message": f"{pc.get('message','')} [uncheckable: {exc}]"})
            continue
        if not passed:
            (blocking if pc["severity"] == "block" else warnings).append(pc)
    return blocking, warnings


# --------------------------------------------------------------------------- #
# Must-not-use boundary pre-filter
# --------------------------------------------------------------------------- #

def match_boundaries(contract: dict[str, Any], deliverable: str) -> list[dict]:
    """Cheap deterministic pre-filter: which must_not_use boundaries does the deliverable
    text keyword-match? A hit here is a *candidate* boundary violation to be confirmed
    (optionally by the LLM in the judgment harness). Zero hits => no LLM call needed.
    """
    text = (deliverable or "").lower()
    hits = []
    for b in contract.get("must_not_use", []):
        if any(kw.lower() in text for kw in b.get("keywords", [])):
            hits.append(b)
    return hits


# --------------------------------------------------------------------------- #
# Metric scoring against the expectation table
# --------------------------------------------------------------------------- #

def _in_tier(value: float, tier: dict[str, Any]) -> bool:
    if tier is None:
        return False
    if "gte" in tier and not value >= tier["gte"]:
        return False
    if "lte" in tier and not value <= tier["lte"]:
        return False
    if "gt" in tier and not value > tier["gt"]:
        return False
    if "lt" in tier and not value < tier["lt"]:
        return False
    if "between" in tier:
        lo, hi = tier["between"]
        if not (lo <= value <= hi):
            return False
    if "not_between" in tier:                  # two-sided: matches when OUTSIDE [lo,hi]
        lo, hi = tier["not_between"]
        if lo <= value <= hi:
            return False
    return True


def score_metric(expectations: dict[str, Any], metric: str, value: float) -> dict[str, Any]:
    """Return {tier: ok|warn|fail|unknown, value, note}.

    Scored BEST-first: a value inside the `ok` band is ok even if the (deliberately wider) `warn`
    band also contains it. Only if it is not ok do we check `fail`, then `warn`.
    """
    spec = expectations.get("metrics", {}).get(metric)
    if spec is None or value is None:
        return {"tier": "unknown", "value": value, "note": "no expectation defined"}
    for tier in ("ok", "fail", "warn"):        # best-first; ok wins ties
        if _in_tier(value, spec.get(tier)):
            return {"tier": tier, "value": value, "note": spec.get("note", "")}
    return {"tier": "unknown", "value": value, "note": spec.get("note", "")}
