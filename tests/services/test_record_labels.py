"""`RecordService.labels`: a record's name worked out from the record when
asked, for anywhere that kept only its id. Nothing is copied into history, and
the cost doesn't grow with the number of ids."""

from __future__ import annotations

import uuid

from sqlalchemy import event

from civex.context import AppContext


def _records(ctx: AppContext, make_schema, make_collection, n: int = 3):
    make_schema("sel", fields=[("number", "integer"), ("note", "string")])
    ctx.schema_svc.update("sel", display_template="{schema} {number}")
    make_collection("study")
    recs = [ctx.record_svc.add("study", "sel", {"number": i + 1}) for i in range(n)]
    ctx.commit()
    return recs


def _names(ctx: AppContext, ids) -> dict[str, str | None]:
    return {
        str(r.id): r.natural_name for r in ctx.record_svc.labels([str(i) for i in ids])
    }


def test_names_come_from_the_record_as_it_is_now(
    ctx: AppContext, make_schema, make_collection
) -> None:
    recs = _records(ctx, make_schema, make_collection)

    names = _names(ctx, [r.id for r in recs])

    assert names == {str(r.id): f"sel {i + 1}" for i, r in enumerate(recs)}


def test_a_change_to_the_record_shows_at_once(
    ctx: AppContext, make_schema, make_collection
) -> None:
    (rec,) = _records(ctx, make_schema, make_collection, n=1)
    assert _names(ctx, [rec.id]) == {str(rec.id): "sel 1"}

    ctx.record_svc.update(str(rec.id), {"number": 99})
    ctx.commit()

    assert _names(ctx, [rec.id]) == {str(rec.id): "sel 99"}


def test_a_change_to_the_name_template_shows_for_every_record(
    ctx: AppContext, make_schema, make_collection
) -> None:
    recs = _records(ctx, make_schema, make_collection)

    ctx.schema_svc.update("sel", display_template="#{number}")
    ctx.commit()

    assert set(_names(ctx, [r.id for r in recs]).values()) == {"#1", "#2", "#3"}


def test_a_name_reaching_through_a_reference_is_worked_out_too(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("species", fields=[("common", "string")])
    make_schema("animal", fields=[("tag", "string"), ("species", "reference")])
    ctx.schema_svc.update("species", display_template="{common}")
    ctx.schema_svc.update_field("animal", "species", restrictions={"schema": "species"})
    ctx.schema_svc.update("animal", display_template="{tag} ({species.common})")
    make_collection("study")
    sp = ctx.record_svc.add("study", "species", {"common": "Orca"})
    an = ctx.record_svc.add("study", "animal", {"tag": "A7", "species": str(sp.id)})
    ctx.commit()

    assert _names(ctx, [an.id]) == {str(an.id): "A7 (Orca)"}

    ctx.record_svc.update(str(sp.id), {"common": "Killer whale"})
    ctx.commit()
    assert _names(ctx, [an.id]) == {str(an.id): "A7 (Killer whale)"}


def test_things_that_are_not_records_are_skipped(
    ctx: AppContext, make_schema, make_collection
) -> None:
    (rec,) = _records(ctx, make_schema, make_collection, n=1)

    got = ctx.record_svc.labels(
        [str(rec.id), "not-an-id", "", str(uuid.uuid4()), str(rec.id)]
    )

    assert [str(r.id) for r in got] == [str(rec.id)]  # once, and only the real one


def test_a_deleted_record_still_has_a_name_and_says_it_is_deleted(
    ctx: AppContext, make_schema, make_collection
) -> None:
    (rec,) = _records(ctx, make_schema, make_collection, n=1)
    ctx.record_svc.delete(str(rec.id))
    ctx.commit()

    (got,) = ctx.record_svc.labels([str(rec.id)])

    assert got.natural_name == "sel 1" and got.deleted_at is not None


def test_the_number_of_queries_does_not_depend_on_the_number_of_ids(
    ctx: AppContext, make_schema, make_collection
) -> None:
    recs = _records(ctx, make_schema, make_collection, n=40)
    engine = ctx._session.get_bind()
    counted: list[str] = []

    def count(conn, cursor, statement, params, context, executemany):
        counted.append(statement)

    def queries_for(ids) -> int:
        counted.clear()
        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.record_svc.labels([str(i) for i in ids])
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(counted)

    few = queries_for([r.id for r in recs[:2]])
    many = queries_for([r.id for r in recs])

    assert many == few  # 40 records cost what 2 do
    assert many <= 6
