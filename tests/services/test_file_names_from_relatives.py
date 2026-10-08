"""A file's download name may use values from the records above it and from
the records their references point at: a Selection's file named from its
Recording, its Encounter and the Species that Encounter references."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from civex.context import AppContext
from civex.domain.dtos import RecordDTO


def _file(sha: str, name: str) -> dict[str, Any]:
    return {"sha256": sha * 64, "filename": name, "size": 3}


def _tree(ctx: AppContext, make_schema, make_collection) -> None:
    make_schema("species", fields=[("common", "string")])
    make_schema("encounter", fields=[("site", "string")])
    ctx.schema_svc.add_field(
        "encounter", "species", "reference", restrictions={"schema": "species"}
    )
    make_schema("recording", fields=[("take", "integer")], parent="encounter")
    make_schema("selection", fields=[("n", "integer")], parent="recording")
    ctx.schema_svc.add_field(
        "selection",
        "table",
        "file",
        restrictions={"filename_template": "{species.common}_{site}_{take:02}_{n}"},
    )
    make_collection("study")
    ctx.commit()


def _selections(ctx: AppContext, count: int, site: str | None = "north") -> list:
    whale = ctx.record_svc.add("study", "species", {"common": "Humpback"})
    enc = ctx.record_svc.add(
        "study", "encounter", {"site": site, "species": str(whale.id)}
    )
    rec = ctx.record_svc.add("study", "recording", {"take": 3}, str(enc.id))
    made = [
        ctx.record_svc.add(
            "study",
            "selection",
            {"n": i, "table": _file(str(i % 10), "raw export.txt")},
            str(rec.id),
        )
        for i in range(count)
    ]
    ctx.commit()
    return made


def _name(record: RecordDTO) -> str:
    return record.data["table"]["resolved_filename"]


def test_a_file_is_named_from_the_records_above_and_their_references(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _tree(ctx, make_schema, make_collection)
    (sel,) = _selections(ctx, 1)

    assert _name(ctx.record_svc.get(str(sel.id))) == "Humpback_north_03_0.txt"
    listed = ctx.record_svc.find("study", schema_name="selection")
    assert [_name(r) for r in listed] == ["Humpback_north_03_0.txt"]


def test_a_blank_value_above_is_skipped_not_a_reason_to_keep_the_original(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _tree(ctx, make_schema, make_collection)
    (sel,) = _selections(ctx, 1, site=None)

    assert _name(ctx.record_svc.get(str(sel.id))) == "Humpback_03_0.txt"


def test_naming_a_page_of_files_costs_the_same_however_many(
    ctx: AppContext, make_schema, make_collection
) -> None:
    _tree(ctx, make_schema, make_collection)

    def statements_for(count: int) -> int:
        _selections(ctx, count)
        seen: list[str] = []
        engine = ctx._session.get_bind()

        def note(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", note)
        try:
            records = ctx.record_svc.find("study", schema_name="selection", limit=500)
        finally:
            event.remove(engine, "before_cursor_execute", note)
        assert all(_name(r).startswith("Humpback_north_03_") for r in records)
        return len(seen)

    assert statements_for(3) == statements_for(30)
