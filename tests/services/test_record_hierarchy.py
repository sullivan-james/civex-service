"""Querying down and up the record hierarchy (encounter -> recording ->
selection): `within` scopes to descendants at any depth, filter leaves can
test an ancestor's or descendant's field, and sort can follow an ancestor."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.query import RecordQuery


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    """
    E1 (Stellwagen)  R1 (96 kHz): S1a(table) S1b(no table)
                     R2 (48 kHz): S2a(table)
    E2 (Georges)     R3 (96 kHz): S3a(no table) S3b(no table)
    """
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("sample_rate", "integer")], parent="encounter")
    make_schema(
        "selection",
        fields=[("selection_table", "string"), ("confidence", "float")],
        parent="recording",
    )
    make_collection("humpback")

    def add(schema, data, parent=None):
        return make_record(
            "humpback",
            schema,
            data,
            parent_record_id=str(parent.id) if parent else None,
        )

    e1 = add("encounter", {"site": "Stellwagen"})
    e2 = add("encounter", {"site": "Georges"})
    r1 = add("recording", {"sample_rate": 96}, e1)
    r2 = add("recording", {"sample_rate": 48}, e1)
    r3 = add("recording", {"sample_rate": 96}, e2)
    s = {
        "S1a": add("selection", {"selection_table": "a.txt", "confidence": 0.9}, r1),
        "S1b": add("selection", {"confidence": 0.3}, r1),
        "S2a": add("selection", {"selection_table": "c.txt", "confidence": 0.6}, r2),
        "S3a": add("selection", {"confidence": 0.8}, r3),
        "S3b": add("selection", {"confidence": 0.2}, r3),
    }
    return {"e1": e1, "e2": e2, "r1": r1, "r2": r2, "r3": r3, **s}


def _ids(records) -> set[str]:
    return {str(r.id) for r in records}


def _q(**kw) -> RecordQuery:
    return RecordQuery(dataset="humpback", **kw)


def test_within_reaches_grandchildren(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(schema="selection", within=str(tree["e1"].id))
    )
    assert _ids(found) == _ids([tree["S1a"], tree["S1b"], tree["S2a"]])


def test_within_direct_parent(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(schema="selection", within=str(tree["r1"].id))
    )
    assert _ids(found) == _ids([tree["S1a"], tree["S1b"]])


def test_within_counts_and_pages_agree(ctx: AppContext, tree):
    query = _q(schema="selection", within=str(tree["e1"].id))
    assert ctx.record_svc.count_records(query) == 3
    assert len(ctx.record_svc.query_records(query, limit=2)) == 2


def test_within_requires_a_schema_and_a_descendant_schema(ctx: AppContext, tree):
    with pytest.raises(ValidationError, match="needs a schema"):
        ctx.record_svc.query_records(_q(within=str(tree["e1"].id)))
    with pytest.raises(ValidationError, match="can't descend"):
        ctx.record_svc.query_records(_q(schema="recording", within=str(tree["S1a"].id)))


def test_within_unknown_record(ctx: AppContext, tree):
    with pytest.raises(NotFoundError):
        ctx.record_svc.query_records(_q(schema="selection", within="ffffffff"))


def test_filter_on_own_field(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(
            schema="selection",
            filter_tree={"field": "selection_table", "op": "is_null"},
        )
    )
    assert _ids(found) == _ids([tree["S1b"], tree["S3a"], tree["S3b"]])


def test_selections_within_a_recording_missing_their_table(ctx: AppContext, tree):
    """The motivating case: drill into a recording, filter to empty tables."""
    found = ctx.record_svc.query_records(
        _q(
            schema="selection",
            within=str(tree["r1"].id),
            filter_tree={"field": "selection_table", "op": "is_null"},
        )
    )
    assert _ids(found) == _ids([tree["S1b"]])


def test_filter_on_ancestor_field_by_schema_qualifier(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(
            schema="selection",
            filter_tree={
                "schema": "recording",
                "field": "sample_rate",
                "op": "gte",
                "value": 96,
            },
        )
    )
    assert _ids(found) == _ids([tree["S1a"], tree["S1b"], tree["S3a"], tree["S3b"]])


def test_inherited_field_name_resolves_to_the_ancestor_that_owns_it(
    ctx: AppContext, tree
):
    # `site` lives on the encounter; a selection's own data never holds it.
    found = ctx.record_svc.query_records(
        _q(
            schema="selection",
            filter_tree={"field": "site", "op": "eq", "value": "Georges"},
        )
    )
    assert _ids(found) == _ids([tree["S3a"], tree["S3b"]])


def test_filter_on_descendant_field_matches_any_descendant(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(
            schema="encounter",
            filter_tree={
                "schema": "selection",
                "field": "selection_table",
                "op": "is_null",
            },
        )
    )
    assert _ids(found) == _ids([tree["e1"], tree["e2"]])

    found = ctx.record_svc.query_records(
        _q(
            schema="recording",
            filter_tree={
                "schema": "selection",
                "field": "confidence",
                "op": "lt",
                "value": 0.25,
            },
        )
    )
    assert _ids(found) == _ids([tree["r3"]])


def test_descendant_filter_ignores_deleted_descendants(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree["S3a"].id))
    ctx.record_svc.delete(str(tree["S3b"].id))
    ctx.commit()
    found = ctx.record_svc.query_records(
        _q(
            schema="recording",
            filter_tree={
                "schema": "selection",
                "field": "selection_table",
                "op": "is_null",
            },
        )
    )
    assert _ids(found) == _ids([tree["r1"]])


def test_mixed_own_ancestor_and_descendant_conditions_in_one_tree(
    ctx: AppContext, tree
):
    # recordings at 96 kHz (own) in a Stellwagen encounter (ancestor) that
    # have a selection with no table (descendant)
    found = ctx.record_svc.query_records(
        _q(
            schema="recording",
            filter_tree={
                "and": [
                    {"field": "sample_rate", "op": "eq", "value": 96},
                    {
                        "schema": "encounter",
                        "field": "site",
                        "op": "eq",
                        "value": "Stellwagen",
                    },
                    {
                        "schema": "selection",
                        "field": "selection_table",
                        "op": "is_null",
                    },
                ]
            },
        )
    )
    assert _ids(found) == _ids([tree["r1"]])


def test_sort_by_an_ancestors_field(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(
            schema="recording",
            sort=[
                {"field": "site", "direction": "asc"},
                {"field": "sample_rate", "direction": "desc"},
            ],
        )
    )
    # Georges < Stellwagen; within Stellwagen, 96 before 48
    assert [str(r.id) for r in found] == [
        str(tree["r3"].id),
        str(tree["r1"].id),
        str(tree["r2"].id),
    ]


@pytest.mark.parametrize(
    "tree_,message",
    [
        ({"field": "nope", "op": "eq", "value": 1}, "Unknown filter field 'nope'"),
        (
            {"schema": "recording", "field": "nope", "op": "eq", "value": 1},
            "Unknown filter field 'nope' on schema 'recording'",
        ),
        (
            {"schema": "encounter2", "field": "site", "op": "eq", "value": 1},
            "neither 'selection' nor one of its ancestors",
        ),
    ],
)
def test_unresolvable_conditions_fail_loudly(ctx: AppContext, tree, tree_, message):
    with pytest.raises(ValidationError, match=message):
        ctx.record_svc.query_records(_q(schema="selection", filter_tree=tree_))


def test_cannot_sort_by_a_descendants_field(ctx: AppContext, tree):
    with pytest.raises(ValidationError, match="many descendants"):
        ctx.record_svc.query_records(
            _q(
                schema="encounter",
                sort=[{"field": "confidence", "schema": "selection"}],
            )
        )


def test_child_counts_per_child_schema(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(schema="recording", within=str(tree["e1"].id)), child_counts=True
    )
    by_id = {str(r.id): r.child_counts for r in found}
    assert by_id[str(tree["r1"].id)] == {"selection": 2}
    assert by_id[str(tree["r2"].id)] == {"selection": 1}


def test_child_counts_empty_for_leaves(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(schema="selection", within=str(tree["r1"].id)), child_counts=True
    )
    assert all(r.child_counts == {} for r in found)


def test_schema_counts_under_a_record_cover_every_descendant_schema(
    ctx: AppContext, tree
):
    counts = ctx.record_svc.schema_counts(
        RecordQuery(dataset="humpback", within=str(tree["e1"].id))
    )
    assert counts == {"recording": 2, "selection": 3}


def test_schema_counts_for_a_whole_collection(ctx: AppContext, tree):
    assert ctx.record_svc.schema_counts(RecordQuery(dataset="humpback")) == {
        "encounter": 2,
        "recording": 3,
        "selection": 5,
    }


def test_derived_columns_carry_inherited_fields(ctx: AppContext, tree):
    found = ctx.record_svc.query_records(
        _q(schema="selection", within=str(tree["r1"].id)),
        columns=["selection_table", "sample_rate", "site"],
    )
    assert {r.derived["site"] for r in found if r.derived} == {"Stellwagen"}
    assert {r.derived["sample_rate"] for r in found if r.derived} == {96}
    # own fields aren't duplicated into `derived`
    assert all("selection_table" not in (r.derived or {}) for r in found)


def test_ancestors_root_first(ctx: AppContext, tree):
    chain = ctx.record_svc.ancestors(ctx.record_svc.get(str(tree["S1a"].id)))
    assert [a.schema_name for a in chain] == ["encounter", "recording"]


def test_delete_matching_deletes_exactly_what_the_query_selects(ctx: AppContext, tree):
    query = _q(
        schema="selection",
        within=str(tree["e1"].id),
        filter_tree={"field": "selection_table", "op": "is_null"},
    )
    assert ctx.record_svc.delete_matching(query) == 1
    ctx.commit()
    remaining = ctx.record_svc.query_records(_q(schema="selection"))
    assert _ids(remaining) == _ids([tree["S1a"], tree["S2a"], tree["S3a"], tree["S3b"]])


def test_stream_pages_through_everything(ctx: AppContext, tree):
    pages = list(ctx.record_svc.stream_records(_q(schema="selection"), page_size=2))
    assert [len(p) for p in pages] == [2, 2, 1]
