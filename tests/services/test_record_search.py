"""Text search matches what a person can see in a record: its values.

A record's `data` is keyed by field ids and holds file references (a sha256,
a size), so a substring match on the stored JSON once found every record for
a short hex-ish term ("a3", "e"). Search now looks only at values: text,
numbers, list items, and the names of files.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.query import RecordQuery


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("code", "string")])
    make_schema(
        "sample",
        fields=[
            ("label", "string"),
            ("note", "longtext"),
            ("depth", "float"),
            ("tags", "tags"),
            ("scan", "file"),
            ("extras", "file_list"),
            ("site", "reference"),
            ("checked", "boolean"),
            ("where", "geo"),
        ],
    )
    make_collection("survey")
    site = make_record("survey", "site", {"code": "north"})
    scan = ctx.file_svc.store_bytes(b"scan bytes", "core_photo.png")
    extra = ctx.file_svc.store_bytes(b"extra bytes", "field_sheet.pdf")
    records = {
        "plain": make_record("survey", "sample", {"label": "Basalt", "depth": 12.5}),
        "tagged": make_record(
            "survey", "sample", {"label": "Shale", "tags": ["fossil", "grey"]}
        ),
        "filed": make_record(
            "survey",
            "sample",
            {
                "label": "Granite",
                "scan": scan.to_dict(),
                "extras": [extra.to_dict()],
                "site": str(site.id),
                "checked": True,
                "where": {"type": "Point", "coordinates": [-3.4, 56.1]},
                "note": "Collected at low tide",
            },
        ),
    }
    return {"site": site, "scan": scan, **records}


def _found(ctx: AppContext, search: str, **kw) -> set[str]:
    return {
        r.data["label"]
        for r in ctx.record_svc.find(
            "survey", schema_name="sample", search=search, **kw
        )
    }


def test_values_are_found(ctx: AppContext, survey) -> None:
    assert _found(ctx, "basalt") == {"Basalt"}  # case-insensitive
    assert _found(ctx, "12.5") == {"Basalt"}  # a number's text
    assert _found(ctx, "fossil") == {"Shale"}  # an item of a list
    assert _found(ctx, "core_photo") == {"Granite"}  # a file's name
    assert _found(ctx, "sheet") == {"Granite"}  # a name in a file list
    assert _found(ctx, "low tide") == {"Granite"}


def test_keys_hashes_and_internals_are_not_searched(ctx: AppContext, survey) -> None:
    sha = survey["scan"].sha256
    schema = ctx.schema_svc.get("sample")
    field_id = str(next(f.id for f in schema.fields if f.name == "label"))
    # A fragment of a file's hash, of a field id, of a JSON key, of a
    # referenced record's id, and of a geometry: none is a value anyone typed.
    for term in (
        sha[:6],
        field_id[:8],
        "sha256",
        "filename",
        "size",
        str(survey["site"].id)[9:18],
        "Point",
        "coordinates",
        "true",
        "%",  # LIKE wildcards are taken literally
        "t_de",
    ):
        assert _found(ctx, term) == set(), term


def test_one_hex_letter_does_not_match_everything(ctx: AppContext, survey) -> None:
    assert _found(ctx, "e") == {"Shale", "Granite"}  # their values have an e
    assert _found(ctx, "a3") == set()


def test_a_record_id_prefix_still_finds_the_record(ctx: AppContext, survey) -> None:
    rid = str(survey["tagged"].id)
    assert _found(ctx, rid[:8]) == {"Shale"}
    assert _found(ctx, rid) == {"Shale"}


def test_search_can_target_one_field(ctx: AppContext, survey) -> None:
    assert _found(ctx, "a", search_fields=["label"]) == {"Basalt", "Shale", "Granite"}
    assert _found(ctx, "tide", search_fields=["label"]) == set()
    assert _found(ctx, "tide", search_fields=["note"]) == {"Granite"}
    assert _found(ctx, "photo", search_fields=["scan", "extras"]) == {"Granite"}


def test_a_field_to_search_must_exist_and_be_searchable(
    ctx: AppContext, survey
) -> None:
    with pytest.raises(ValidationError, match="no field"):
        _found(ctx, "x", search_fields=["nope"])
    with pytest.raises(ValidationError, match="can't be searched"):
        _found(ctx, "x", search_fields=["site"])
    with pytest.raises(ValidationError, match="choose a schema"):
        ctx.record_svc.resolve(
            RecordQuery(dataset="survey", search="x", search_fields=["label"])
        )


def test_every_search_follows_the_same_rule(ctx: AppContext, survey) -> None:
    """The explorer, its count, reference pickers, the jump-to box and every
    collection's list agree."""
    sha = survey["scan"].sha256[:6]
    assert ctx.record_svc.count("survey", schema_name="sample", search=sha) == 0
    assert ctx.record_svc.find_by_schema("sample", search=sha) == []
    assert ctx.record_svc.count_by_schema_search("sample", search=sha) == 0
    assert ctx.record_svc.search(sha) == []
    assert ctx.record_svc.find("survey", search=sha) == []  # every schema

    assert {r.data["label"] for r in ctx.record_svc.search("granite")} == {"Granite"}
    assert [
        r.data["label"] for r in ctx.record_svc.find_by_schema("sample", search="photo")
    ] == ["Granite"]
    assert ctx.record_svc.count_by_schema_search("sample", search="photo") == 1
    # Across every schema a site's code is found as well as a sample's label.
    assert {r.schema_name for r in ctx.record_svc.find("survey", search="n")} == {
        "site",
        "sample",
    }


def test_a_search_costs_the_same_however_many_records(ctx: AppContext, survey) -> None:
    """The match is made in SQL: no record is looked at in Python, so ten
    times the records is the same number of statements."""
    engine = ctx._session.get_bind()
    counted: list[str] = []

    def count(conn, cursor, statement, params, context, executemany):
        counted.append(statement)

    def statements() -> int:
        counted.clear()
        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.record_svc.count("survey", schema_name="sample", search="extra")
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(counted)

    def add(n: int) -> None:
        for i in range(n):
            ctx.record_svc.add("survey", "sample", {"label": f"Extra {i}"})
        ctx.commit()

    add(3)
    few = statements()
    add(30)
    assert statements() == few
