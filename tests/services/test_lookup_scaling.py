"""Writing a record must not cost more as data grows, and must not re-resolve
the same schema over and over: a collection lookup must not count its records,
and one add resolves its schema (and ancestors) once."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from civex.context import AppContext


@contextmanager
def count_statements(ctx: AppContext):
    seen: list[str] = []

    def record(conn, cursor, statement, *_):
        seen.append(statement)

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _schema_fetches(statements: list[str]) -> list[str]:
    return [s for s in statements if "FROM schemas" in s and "dataset_schemas" not in s]


def test_collection_lookup_counts_records_only_when_asked(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient")
    make_collection("study")
    make_record("study", "patient", {})
    make_record("study", "patient", {})
    repo = ctx.dataset_svc._datasets

    assert repo.get_by_name("study").record_count == 2
    with count_statements(ctx) as seen:
        assert repo.get_by_name("study", with_count=False).record_count == 0
    assert not any("count(" in s.lower() for s in seen)


def test_adding_a_record_never_counts_the_collection(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")
    make_record("study", "patient", {"name": "warm up"})

    with count_statements(ctx) as seen:
        ctx.record_svc.add("study", "patient", {"name": "x"})

    assert not any("count(" in s.lower() for s in seen)


def test_adding_records_issues_the_same_queries_however_many_exist(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")

    def queries_for_one_add() -> int:
        with count_statements(ctx) as seen:
            ctx.record_svc.add("study", "patient", {"name": "x"})
        return len(seen)

    queries_for_one_add()  # primes caches
    few = queries_for_one_add()
    for _ in range(40):
        make_record("study", "patient", {"name": "filler"})
    many = queries_for_one_add()

    assert many == few


def test_adding_a_deep_child_record_resolves_each_schema_once(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("encounter", fields=[("code", "string")])
    make_schema("recording", fields=[("file", "string")], parent="encounter")
    make_schema("selection", fields=[("label", "string")], parent="recording")
    make_collection("study")
    enc = ctx.record_svc.add("study", "encounter", {"code": "e"})
    rec = ctx.record_svc.add(
        "study", "recording", {"file": "f"}, parent_record_id=str(enc.id)
    )

    with count_statements(ctx) as seen:
        ctx.record_svc.add(
            "study", "selection", {"label": "x"}, parent_record_id=str(rec.id)
        )

    # Without resolving once, every helper re-walked the chain: dozens of
    # schema fetches for a three-level record.
    # selection, recording and encounter once each, plus the schema row behind
    # the parent and the created record. Re-resolving per helper took ~20.
    assert len(_schema_fetches(seen)) <= 5


def test_listing_records_costs_the_same_queries_for_a_page_of_any_size(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("patient", fields=[("name", "string")])
    make_collection("study")

    def queries_for_page(limit: int) -> int:
        with count_statements(ctx) as seen:
            ctx.record_svc.find(
                "study", schema_name="patient", filters=[], limit=limit
            )
        return len(seen)

    for i in range(40):
        ctx.record_svc.add("study", "patient", {"name": f"p{i}"})
    ctx.commit()

    assert queries_for_page(40) == queries_for_page(3)
