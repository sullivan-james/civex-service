"""Multi-operator, AND/OR grouped filtering for RecordService.find()/count()."""
from __future__ import annotations

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
import pytest


@pytest.fixture()
def employees(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema(
        "employee",
        fields=[
            ("name", "string"),
            ("age", "integer"),
            ("active", "boolean"),
            ("dept", "string"),
        ],
    )
    make_collection("acme")
    alice = make_record(
        "acme", "employee", {"name": "Alice", "age": 30, "active": True, "dept": "eng"}
    )
    bob = make_record(
        "acme", "employee", {"name": "Bob", "age": 25, "active": False, "dept": "sales"}
    )
    carol = make_record(
        "acme", "employee", {"name": "Carol", "age": 40, "active": True, "dept": "eng"}
    )
    dave = make_record("acme", "employee", {"name": "Dave"})
    return {"alice": alice, "bob": bob, "carol": carol, "dave": dave}


def _names(records) -> set[str]:
    return {r.data["name"] for r in records}


def test_eq_leaf(ctx: AppContext, employees):
    tree = {"field": "dept", "op": "eq", "value": "eng"}
    records = ctx.record_svc.find("acme", schema_name="employee", filter_tree=tree)
    assert _names(records) == {"Alice", "Carol"}
    assert ctx.record_svc.count("acme", schema_name="employee", filter_tree=tree) == 2


def test_gt_gte_lt_lte(ctx: AppContext, employees):
    assert _names(
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "age", "op": "gt", "value": 30},
        )
    ) == {"Carol"}
    assert _names(
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "age", "op": "gte", "value": 30},
        )
    ) == {"Alice", "Carol"}
    assert _names(
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "age", "op": "lt", "value": 30},
        )
    ) == {"Bob"}
    assert _names(
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "age", "op": "lte", "value": 30},
        )
    ) == {"Alice", "Bob"}


def test_ne_excludes_matching_and_missing(ctx: AppContext, employees):
    # Dave has no dept at all, so a strict "not equal to eng" excludes him too.
    records = ctx.record_svc.find(
        "acme", schema_name="employee",
        filter_tree={"field": "dept", "op": "ne", "value": "eng"},
    )
    assert _names(records) == {"Bob"}


def test_contains_is_case_insensitive_substring(ctx: AppContext, employees):
    records = ctx.record_svc.find(
        "acme", schema_name="employee",
        filter_tree={"field": "name", "op": "contains", "value": "AR"},
    )
    assert _names(records) == {"Carol"}


def test_in_operator(ctx: AppContext, employees):
    records = ctx.record_svc.find(
        "acme", schema_name="employee",
        filter_tree={"field": "dept", "op": "in", "value": ["eng", "sales"]},
    )
    assert _names(records) == {"Alice", "Bob", "Carol"}


def test_is_null(ctx: AppContext, employees):
    missing_age = ctx.record_svc.find(
        "acme", schema_name="employee",
        filter_tree={"field": "age", "op": "is_null"},
    )
    assert _names(missing_age) == {"Dave"}

    has_age = ctx.record_svc.find(
        "acme", schema_name="employee",
        filter_tree={"field": "age", "op": "is_null", "value": False},
    )
    assert _names(has_age) == {"Alice", "Bob", "Carol"}


def test_and_group(ctx: AppContext, employees):
    tree = {
        "and": [
            {"field": "dept", "op": "eq", "value": "eng"},
            {"field": "age", "op": "gte", "value": 30},
        ]
    }
    assert _names(
        ctx.record_svc.find("acme", schema_name="employee", filter_tree=tree)
    ) == {"Alice", "Carol"}


def test_or_group(ctx: AppContext, employees):
    tree = {
        "or": [
            {"field": "dept", "op": "eq", "value": "sales"},
            {"field": "age", "op": "gt", "value": 35},
        ]
    }
    assert _names(
        ctx.record_svc.find("acme", schema_name="employee", filter_tree=tree)
    ) == {"Bob", "Carol"}


def test_nested_groups(ctx: AppContext, employees):
    # eng AND (age >= 40 OR active == false) -> just Carol
    tree = {
        "and": [
            {"field": "dept", "op": "eq", "value": "eng"},
            {
                "or": [
                    {"field": "age", "op": "gte", "value": 40},
                    {"field": "active", "op": "eq", "value": False},
                ]
            },
        ]
    }
    assert _names(
        ctx.record_svc.find("acme", schema_name="employee", filter_tree=tree)
    ) == {"Carol"}


def test_combines_with_legacy_where_filters(ctx: AppContext, employees):
    # where=dept=eng (legacy simple form) AND age > 35 (new tree) -> Carol only.
    records = ctx.record_svc.find(
        "acme",
        schema_name="employee",
        filters=["dept=eng"],
        filter_tree={"field": "age", "op": "gt", "value": 35},
    )
    assert _names(records) == {"Carol"}


def test_unknown_operator_rejected(ctx: AppContext, employees):
    with pytest.raises(ValidationError, match="Unknown filter operator"):
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "age", "op": "between", "value": [1, 2]},
        )


def test_in_requires_list_value(ctx: AppContext, employees):
    with pytest.raises(ValidationError, match="requires a list"):
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={"field": "dept", "op": "in", "value": "eng"},
        )


def test_malformed_group_rejected(ctx: AppContext, employees):
    with pytest.raises(ValidationError, match="exactly one key"):
        ctx.record_svc.find(
            "acme", schema_name="employee",
            filter_tree={
                "and": [{"field": "dept", "op": "eq", "value": "eng"}],
                "or": [{"field": "dept", "op": "eq", "value": "sales"}],
            },
        )
