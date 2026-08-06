"""Load and reason over component contracts.

This is the enforcement engine both tracks share. It does four things:

  1. load_contract / validate_contract  -> read a contract yaml + check it against the JSON Schema.
  2. evaluate_preconditions             -> run each `assert` against declared/measured facts.
  3. match_boundaries                    -> cheap keyword pre-filter of must_not_use vs a deliverable.
  4. score_metric / load_expectations    -> tier a measured metric against the expected-range table.

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


# --------------------------------------------------------------------------- #
# Loading & schema validation
# --------------------------------------------------------------------------- #

def load_contract(tool_id: str) -> dict[str, Any]:
    path = TOOLS_ROOT / tool_id / "contract.yml"
    with open(path) as fh:
        return yaml.safe_load(fh)


def validate_contract(contract: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the contract is malformed."""
    import json

    import jsonschema

    with open(SCHEMA_PATH) as fh:
        schema = json.load(fh)
    jsonschema.validate(contract, schema)


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
