"""The restricted `if:` expression evaluator (CIVEX-129): comparisons/and/or/
not over `step_id.output` and `__input__.x` references only -- never
eval()/compile()'d.
"""

from __future__ import annotations

import pytest

from civex.workflows.conditions import (
    SKIPPED,
    ConditionError,
    condition_refs,
    evaluate_condition,
)


def test_bare_reference_is_truthy_checked():
    assert evaluate_condition("one.ok", {"one": {"ok": True}}) is True
    assert evaluate_condition("one.ok", {"one": {"ok": False}}) is False


def test_equality_comparison():
    assert evaluate_condition("one.status == 'done'", {"one": {"status": "done"}})
    assert not evaluate_condition("one.status == 'done'", {"one": {"status": "pending"}})


def test_numeric_comparison():
    assert evaluate_condition("one.count > 5", {"one": {"count": 10}})
    assert not evaluate_condition("one.count > 5", {"one": {"count": 1}})


def test_and_or_not():
    outputs = {"one": {"a": True, "b": False}}
    assert evaluate_condition("one.a and not one.b", outputs)
    assert not evaluate_condition("one.a and one.b", outputs)
    assert evaluate_condition("one.b or one.a", outputs)


def test_manual_run_input_reference():
    assert evaluate_condition("__input__.flag == True", {"__input__": {"flag": True}})


def test_chained_comparison():
    assert evaluate_condition("1 < one.count < 10", {"one": {"count": 5}})
    assert not evaluate_condition("1 < one.count < 10", {"one": {"count": 20}})


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "one.value + 1",
        "[x for x in range(3)]",
        "one.method()",
        "one.value[0]",
        "lambda: True",
    ],
)
def test_unsafe_expressions_are_rejected(expr):
    with pytest.raises(ConditionError):
        evaluate_condition(expr, {"one": {"value": 1}})


def test_syntax_error_is_rejected():
    with pytest.raises(ConditionError):
        evaluate_condition("one.value ==", {"one": {"value": 1}})


def test_reference_to_step_that_has_not_run_yet_errors():
    with pytest.raises(ConditionError, match="has not run yet"):
        evaluate_condition("missing.value", {})


def test_reference_to_unknown_output_errors():
    with pytest.raises(ConditionError, match="no output"):
        evaluate_condition("one.nope", {"one": {"value": 1}})


def test_condition_refs_extracts_step_and_output():
    assert condition_refs("one.a and __input__.b") == [("one", "a"), ("__input__", "b")]


def test_condition_refs_rejects_unsafe_expression():
    with pytest.raises(ConditionError):
        condition_refs("one.value + 1")


def test_skipped_marker_is_falsy():
    assert not SKIPPED
    assert bool(SKIPPED) is False
