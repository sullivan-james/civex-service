"""Restricted boolean expression evaluator for `StepDef.if_` (CIVEX-129).

A step's `if:` is parsed with `ast.parse` but never `eval()`/`compile()`'d --
only a small whitelist of node types is walked: `and`/`or`/`not`, comparisons
(`==`, `!=`, `<`, `<=`, `>`, `>=`), literals, and `step_id.output_name` /
`__input__.x` references resolved the same way `inputs:` are. Anything else
(calls, subscripts, arithmetic, comprehensions, ...) is rejected before it's
ever evaluated.
"""

from __future__ import annotations

import ast
from typing import Any

_ALLOWED_COMPARE_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


class ConditionError(ValueError):
    """An `if:` expression is malformed, unsafe, or references something
    that can't be resolved."""


class Skipped:
    """Sentinel substituted for every output of a step whose `if:` was
    falsy, so downstream `inputs:`/`if:` references get a value distinct
    from any real output instead of a `KeyError`. Falsy, so a downstream
    `if:` that chains off a skipped step's output (e.g. `if: upstream.ok`)
    skips too without executor needing to propagate skips explicitly."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<skipped>"


SKIPPED = Skipped()


class _SkippedOutputs(dict[str, Any]):
    """Placeholder `step_outputs` entry for a skipped step: every output
    name resolves to SKIPPED, since a skipped step's plugin never ran and
    so never declared which specific outputs it would have produced. A
    `dict` subclass so it satisfies the same `dict[str, Any]` type the
    executor otherwise stores per step."""

    def __contains__(self, key: object) -> bool:
        return True

    def __missing__(self, key: str) -> Any:
        return SKIPPED


SKIPPED_OUTPUTS = _SkippedOutputs()


def parse_condition(expr: str) -> ast.expr:
    """Parse `expr` and validate it uses only the safe subset. Returns the
    AST body (not yet evaluated) for reuse by both static reference
    checking (contract_validation) and run-time evaluation (executor)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ConditionError(f"Invalid 'if' expression {expr!r}: {e}") from e
    _validate_node(tree.body, expr)
    return tree.body


def _validate_node(node: ast.expr, expr: str) -> None:
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ConditionError(f"Unsupported operator in 'if' expression {expr!r}")
        for value in node.values:
            _validate_node(value, expr)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            raise ConditionError(f"Unsupported operator in 'if' expression {expr!r}")
        _validate_node(node.operand, expr)
        return

    if isinstance(node, ast.Compare):
        _validate_node(node.left, expr)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _ALLOWED_COMPARE_OPS:
                raise ConditionError(
                    f"Unsupported comparison operator in 'if' expression {expr!r}"
                )
            _validate_node(comparator, expr)
        return

    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and isinstance(node.ctx, ast.Load)
    ):
        return

    if isinstance(node, ast.Constant):
        return

    raise ConditionError(f"Unsupported expression in 'if' {expr!r}: {ast.dump(node)}")


def condition_refs(expr: str) -> list[tuple[str, str]]:
    """Every `step_id.output_name` (or `__input__.x`) reference an `if:`
    expression reads, for static validation against known steps -- mirrors
    `inputs:` reference checking in contract_validation."""
    body = parse_condition(expr)
    return [
        (node.value.id, node.attr)
        for node in ast.walk(body)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    ]


def evaluate_condition(expr: str, step_outputs: dict[str, dict[str, Any]]) -> bool:
    """Evaluate an already-save-time-validated `if:` expression against the
    outputs produced so far in a workflow run."""
    body = parse_condition(expr)
    try:
        return bool(_eval(body, expr, step_outputs))
    except ConditionError:
        raise
    except Exception as e:
        raise ConditionError(f"Error evaluating 'if' expression {expr!r}: {e}") from e


def _eval(node: ast.expr, expr: str, step_outputs: dict[str, dict[str, Any]]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = (_eval(v, expr, step_outputs) for v in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)

    if isinstance(node, ast.UnaryOp):
        return not _eval(node.operand, expr, step_outputs)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, expr, step_outputs)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, expr, step_outputs)
            if not _ALLOWED_COMPARE_OPS[type(op)](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return _resolve_ref(node.value.id, node.attr, expr, step_outputs)

    if isinstance(node, ast.Constant):
        return node.value

    raise ConditionError(f"Unsupported expression in 'if' {expr!r}")


def _resolve_ref(
    step_id: str,
    output_name: str,
    expr: str,
    step_outputs: dict[str, dict[str, Any]],
) -> Any:
    if step_id not in step_outputs:
        raise ConditionError(
            f"'if' expression {expr!r} references step '{step_id}', which has "
            "not run yet"
        )
    outputs = step_outputs[step_id]
    if output_name not in outputs:
        raise ConditionError(
            f"'if' expression {expr!r} references '{step_id}.{output_name}', "
            f"but step '{step_id}' has no output '{output_name}'"
        )
    return outputs[output_name]
