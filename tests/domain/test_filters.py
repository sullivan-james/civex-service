"""Parsing of the filter-tree wire format, including the optional `schema`
qualifier that lets a leaf test an ancestor's or descendant's field."""

from __future__ import annotations

import pytest

from civex.domain.exceptions import ValidationError
from civex.domain.filters import (
    FilterCondition,
    FilterGroup,
    leaves,
    map_leaves,
    parse_filter_tree,
)


def test_leaf_without_schema_qualifier():
    node = parse_filter_tree({"field": "age", "op": "gte", "value": 3})
    assert isinstance(node, FilterCondition)
    assert (node.field, node.op, node.value, node.schema) == ("age", "gte", 3, None)


def test_leaf_with_schema_qualifier():
    node = parse_filter_tree(
        {"schema": "selection", "field": "selection_table", "op": "is_null"}
    )
    assert isinstance(node, FilterCondition)
    assert node.schema == "selection"
    assert node.value is True  # is_null defaults to "is empty"


@pytest.mark.parametrize("bad", ["", 3, []])
def test_schema_qualifier_must_be_a_non_empty_string(bad):
    with pytest.raises(ValidationError, match="'schema'"):
        parse_filter_tree({"schema": bad, "field": "f", "op": "eq", "value": 1})


def test_groups_nest_and_leaves_walks_them_all():
    node = parse_filter_tree(
        {
            "and": [
                {"field": "a", "op": "eq", "value": 1},
                {
                    "or": [
                        {"field": "b", "op": "eq", "value": 2},
                        {"field": "c", "op": "is_null"},
                    ]
                },
            ]
        }
    )
    assert isinstance(node, FilterGroup)
    assert [leaf.field for leaf in leaves(node)] == ["a", "b", "c"]


def test_map_leaves_rewrites_every_condition_and_keeps_the_shape():
    node = parse_filter_tree(
        {
            "or": [
                {"field": "a", "op": "eq", "value": 1},
                {"field": "b", "op": "eq", "value": 2},
            ]
        }
    )
    mapped = map_leaves(
        node, lambda leaf: FilterCondition(leaf.field.upper(), leaf.op, leaf.value)
    )
    assert isinstance(mapped, FilterGroup) and mapped.op == "or"
    assert [leaf.field for leaf in leaves(mapped)] == ["A", "B"]


@pytest.mark.parametrize(
    "raw,message",
    [
        ("nope", "must be an object"),
        ({"and": []}, "non-empty list"),
        ({"field": "a"}, "'field' and 'op'"),
        ({"field": "a", "op": "like", "value": 1}, "Unknown filter operator"),
        ({"field": "a", "op": "in", "value": 1}, "requires a list"),
    ],
)
def test_structural_errors(raw, message):
    with pytest.raises(ValidationError, match=message):
        parse_filter_tree(raw)
