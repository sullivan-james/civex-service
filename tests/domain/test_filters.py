"""evaluate_filter_tree: the in-memory counterpart to the SQL filter used by
view export, which spans every dataset for a schema rather than running one
query the SQL filter could attach a WHERE clause to."""

from __future__ import annotations

import pytest

from civex.domain.filters import evaluate_filter_tree, parse_filter_tree


def _eval(tree: dict, data: dict) -> bool:
    return evaluate_filter_tree(parse_filter_tree(tree), data)


@pytest.mark.parametrize(
    "op,value,data_value,expected",
    [
        ("eq", "active", "active", True),
        ("eq", "active", "inactive", False),
        ("ne", "active", "inactive", True),
        ("gt", 10, 20, True),
        ("gt", 10, 5, False),
        ("gte", 10, 10, True),
        ("lt", 10, 5, True),
        ("lte", 10, 10, True),
        ("contains", "wor", "hello world", True),
        ("contains", "xyz", "hello world", False),
    ],
)
def test_leaf_operators(op, value, data_value, expected):
    assert _eval({"field": "f", "op": op, "value": value}, {"f": data_value}) is expected


def test_in_operator():
    assert _eval({"field": "f", "op": "in", "value": [1, 2, 3]}, {"f": 2}) is True
    assert _eval({"field": "f", "op": "in", "value": [1, 2, 3]}, {"f": 9}) is False


def test_is_null_true_and_false():
    assert _eval({"field": "f", "op": "is_null"}, {}) is True
    assert _eval({"field": "f", "op": "is_null", "value": False}, {"f": "x"}) is True
    assert _eval({"field": "f", "op": "is_null", "value": False}, {}) is False


@pytest.mark.parametrize("op", ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"])
def test_missing_field_never_matches_except_is_null(op):
    value = [1] if op == "in" else "x"
    assert _eval({"field": "missing", "op": op, "value": value}, {}) is False


def test_type_mismatch_comparison_does_not_raise():
    assert _eval({"field": "f", "op": "gt", "value": 10}, {"f": "not-a-number"}) is False


def test_and_group_requires_every_condition():
    tree = {
        "and": [
            {"field": "status", "op": "eq", "value": "active"},
            {"field": "age", "op": "gte", "value": 18},
        ]
    }
    assert _eval(tree, {"status": "active", "age": 20}) is True
    assert _eval(tree, {"status": "active", "age": 10}) is False


def test_or_group_requires_any_condition():
    tree = {
        "or": [
            {"field": "status", "op": "eq", "value": "active"},
            {"field": "status", "op": "eq", "value": "pending"},
        ]
    }
    assert _eval(tree, {"status": "pending"}) is True
    assert _eval(tree, {"status": "closed"}) is False


def test_nested_groups():
    tree = {
        "and": [
            {"field": "status", "op": "eq", "value": "active"},
            {
                "or": [
                    {"field": "region", "op": "eq", "value": "west"},
                    {"field": "region", "op": "eq", "value": "east"},
                ]
            },
        ]
    }
    assert _eval(tree, {"status": "active", "region": "east"}) is True
    assert _eval(tree, {"status": "active", "region": "north"}) is False
