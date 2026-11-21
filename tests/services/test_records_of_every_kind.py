"""A list of every kind of record at once (`RecordQuery` with no schema): in a
collection, in every collection, and beneath one record; searched, filtered by
open notes, sorted by what every record has; a field filter or sort refused;
and the cost of a page."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.query import RecordQuery


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("rate", "string")], parent="encounter")
    make_schema("selection", fields=[("table", "string")], parent="recording")
    make_collection("survey")
    make_collection("pilot")
    enc = make_record("survey", "encounter", {"site": "reef"})
    rec = make_record(
        "survey", "recording", {"rate": "48"}, parent_record_id=str(enc.id)
    )
    sel = make_record(
        "survey", "selection", {"table": "a.txt"}, parent_record_id=str(rec.id)
    )
    other = make_record("pilot", "encounter", {"site": "bay"})
    return enc, rec, sel, other


def _kinds(ctx: AppContext, query: RecordQuery) -> list[str]:
    return sorted(r.schema_name for r in ctx.record_svc.query_records(query))


def test_every_kind_is_listed_and_counted(ctx: AppContext, tree):
    assert _kinds(ctx, RecordQuery(dataset="survey")) == [
        "encounter",
        "recording",
        "selection",
    ]
    assert len(ctx.record_svc.query_records(RecordQuery())) == 4
    assert ctx.record_svc.count_records(RecordQuery()) == 4
    assert ctx.record_svc.count_records(RecordQuery(dataset="pilot")) == 1


def test_beneath_a_record_is_everything_under_it(ctx: AppContext, tree):
    enc, rec, sel, _ = tree
    assert _kinds(ctx, RecordQuery(within=str(enc.id))) == ["recording", "selection"]
    assert _kinds(ctx, RecordQuery(within=str(rec.id))) == ["selection"]
    assert _kinds(ctx, RecordQuery(within=str(sel.id))) == []
    assert ctx.record_svc.count_records(RecordQuery(within=str(enc.id))) == 2


def test_open_notes_are_found_on_any_kind(ctx: AppContext, tree):
    _, _, sel, other = tree
    ctx.note_svc.add(str(sel.id), "wrong table")
    ctx.note_svc.add(str(other.id), "which bay?")
    ctx.commit()
    found = ctx.record_svc.query_records(
        RecordQuery(filter_tree={"field": "@open_notes", "op": "eq", "value": True})
    )
    assert {(r.schema_name, r.latest_note) for r in found} == {
        ("selection", "wrong table"),
        ("encounter", "which bay?"),
    }


def test_search_and_sorts_that_every_record_has(ctx: AppContext, tree):
    assert _kinds(ctx, RecordQuery(search="a.txt")) == ["selection"]
    by_kind = ctx.record_svc.query_records(
        RecordQuery(sort=[{"field": "@kind", "direction": "desc"}])
    )
    assert [r.schema_name for r in by_kind] == [
        "selection",
        "recording",
        "encounter",
        "encounter",
    ]
    by_collection = ctx.record_svc.query_records(
        RecordQuery(sort=[{"field": "@collection"}, {"field": "@updated_at"}])
    )
    assert by_collection[0].dataset_name == "pilot"
    # The same sorts work on a list of one kind.
    one = ctx.record_svc.query_records(
        RecordQuery(schema="encounter", sort=[{"field": "@collection"}])
    )
    assert [r.data["site"] for r in one] == ["bay", "reef"]


def test_a_field_filter_or_sort_needs_a_kind(ctx: AppContext, tree):
    with pytest.raises(ValidationError, match="choose a kind"):
        ctx.record_svc.query_records(
            RecordQuery(filter_tree={"field": "site", "op": "eq", "value": "reef"})
        )
    with pytest.raises(ValidationError, match="choose a kind"):
        ctx.record_svc.count_records(
            RecordQuery(
                filter_tree={
                    "and": [
                        {"field": "@open_notes", "op": "eq", "value": True},
                        {"field": "site", "op": "eq", "value": "reef"},
                    ]
                }
            )
        )
    with pytest.raises(ValidationError, match="choose a kind"):
        ctx.record_svc.query_records(RecordQuery(sort=[{"field": "site"}]))


@contextmanager
def _statements(ctx: AppContext):
    seen: list[str] = []

    def record(conn, cursor, statement, *_):
        seen.append(statement)

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_a_page_of_every_kind_costs_the_same_however_many(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("rate", "string")], parent="encounter")
    make_collection("few")
    make_collection("many")
    for name, n in (("few", 2), ("many", 15)):
        for i in range(n):
            enc = make_record(name, "encounter", {"site": f"{name}{i}"})
            rec = make_record(
                name, "recording", {"rate": "48"}, parent_record_id=str(enc.id)
            )
            ctx.note_svc.add(str(rec.id), "check the rate")
    ctx.commit()

    def cost(name: str) -> int:
        query = RecordQuery(dataset=name, sort=[{"field": "@kind"}])
        with _statements(ctx) as seen:
            ctx.record_svc.query_records(query, child_counts=True)
            ctx.record_svc.count_records(query)
        return len(seen)

    assert cost("few") == cost("many")
