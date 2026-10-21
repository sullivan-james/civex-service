"""A field filled from a file's name as the record is saved: the
`from_filename` restriction (`domain/filename_extract`, applied by
`RecordService._fill_from_filenames`, checked by `SchemaService`)."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain import filename_extract
from civex.domain.exceptions import (
    DuplicateRecordError,
    FieldValueError,
    ValidationError,
)


def _file(ctx: AppContext, name: str) -> dict:
    return ctx.file_svc.store_bytes(b"x", name).to_dict()


def _rule(field: str, pattern: str) -> dict:
    return {"from_filename": {"field": field, "pattern": pattern}}


@pytest.fixture()
def recordings(ctx: AppContext, make_schema, make_collection):
    """A recording with an `audio` file and fields read from its name."""
    make_collection("study")
    make_schema("recording", fields=[("audio", "file")])
    ctx.schema_svc.add_field(
        "recording", "name", "string", restrictions=_rule("audio", r"^(.+)\.wav$")
    )
    ctx.schema_svc.add_field(
        "recording", "take", "integer", restrictions=_rule("audio", r"_t(\d+)")
    )
    ctx.schema_svc.add_field(
        "recording",
        "start",
        "datetime",
        restrictions=_rule("audio", "YYYYMMDD[-_]HHmmSS"),
    )
    ctx.commit()


# ---------------------------------------------------------------------------
# the pure rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,kind,filename,expected",
    [
        (r"site-([A-Z]+)_", "string", "site-NR_2024.jpg", "NR"),
        (r"\d+", "integer", "take_042.wav", 42),
        (r"depth_([\d.]+)m", "float", "depth_12.5m.csv", 12.5),
        ("YYYY-MM-DD", "date", "site-NR_2024-03-15.jpg", "2024-03-15"),
        (
            "YYYYMMDD[-_]HHmmSS",
            "datetime",
            "20240315_093000.wav",
            "2024-03-15T09:30:00",
        ),
        (r"take_(\d+)", "integer", "nothing_here.wav", None),
    ],
)
def test_extract_reads_the_value_or_nothing(pattern, kind, filename, expected):
    assert filename_extract.extract(filename, pattern, kind) == expected


@pytest.mark.parametrize(
    "pattern,kind,message",
    [
        ("(", "string", "regular expression"),
        ("", "string", "empty"),
        ("YYYYMMDD", "string", None),  # a plain regex: fine for text
        ("HHmmSS", "datetime", "YYYY MM DD"),
        ("YYYY-MM", "date", "DD"),
        (r"(\d+)", "boolean", "can't be filled"),
    ],
)
def test_compile_pattern_refuses_what_cannot_work(pattern, kind, message):
    if message is None:
        filename_extract.compile_pattern(pattern, kind)
        return
    with pytest.raises(ValueError, match=message):
        filename_extract.compile_pattern(pattern, kind)


def test_a_match_that_is_not_the_type_is_an_error():
    with pytest.raises(ValueError, match="not a whole number"):
        filename_extract.extract("take_ab.wav", r"take_(\w+)", "integer")
    with pytest.raises(ValueError, match="not a date"):
        filename_extract.extract("x_20241399.wav", "YYYYMMDD", "date")


def test_first_filename_reads_a_file_or_the_first_of_a_list():
    assert filename_extract.first_filename({"filename": "a.wav"}) == "a.wav"
    assert (
        filename_extract.first_filename([{"filename": "a.wav"}, {"filename": "b"}])
        == "a.wav"
    )
    assert filename_extract.first_filename([]) is None
    assert filename_extract.first_filename(None) is None
    assert filename_extract.first_filename("a.wav") is None


# ---------------------------------------------------------------------------
# deriving on add and update
# ---------------------------------------------------------------------------


def test_blank_fields_are_filled_from_the_file_name(ctx: AppContext, recordings):
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "20240315_093000_t3.wav")}
    )
    assert rec.data["name"] == "20240315_093000_t3"
    assert rec.data["take"] == 3
    assert rec.data["start"] == "2024-03-15T09:30:00+00:00"


def test_a_typed_value_is_kept(ctx: AppContext, recordings):
    rec = ctx.record_svc.add(
        "study",
        "recording",
        {"audio": _file(ctx, "20240315_093000_t3.wav"), "name": "dawn chorus"},
    )
    assert rec.data["name"] == "dawn chorus"
    assert rec.data["take"] == 3


def test_a_name_the_pattern_does_not_fit_leaves_the_field_blank(
    ctx: AppContext, recordings
):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "x.wav")})
    assert rec.data["name"] == "x"
    assert rec.data.get("take") is None
    assert rec.data.get("start") is None


def test_no_file_means_nothing_is_derived(ctx: AppContext, recordings):
    rec = ctx.record_svc.add("study", "recording", {})
    assert rec.data.get("name") is None


def test_a_value_that_is_not_the_type_is_refused_naming_the_field(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    take = ctx.schema_svc.add_field(
        "doc", "take", "integer", restrictions=_rule("attachment", r"take_(\w+)")
    )
    with pytest.raises(FieldValueError, match="'take'.*take_ab.pdf") as e:
        ctx.record_svc.add("study", "doc", {"attachment": _file(ctx, "take_ab.pdf")})
    assert e.value.path == f"data.{take.id}"


def test_the_derived_value_is_held_to_the_field_rules(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    ctx.schema_svc.add_field(
        "doc",
        "take",
        "integer",
        restrictions={**_rule("attachment", r"take_(\d+)"), "max": 10},
    )
    with pytest.raises(ValidationError, match="exceeds maximum"):
        ctx.record_svc.add("study", "doc", {"attachment": _file(ctx, "take_42.pdf")})


def test_the_derived_value_satisfies_and_is_held_to_a_unique_key(
    ctx: AppContext, recordings
):
    ctx.schema_svc.set_unique_keys("recording", [["name"]])
    ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "b_t1.wav")})
    with pytest.raises(DuplicateRecordError):
        ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})


def test_a_file_list_gives_its_first_file(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("doc", fields=[("photos", "file_list")])
    ctx.schema_svc.add_field(
        "doc", "site", "string", restrictions=_rule("photos", r"^([A-Z]+)_")
    )
    rec = ctx.record_svc.add(
        "study",
        "doc",
        {"photos": [_file(ctx, "NR_1.jpg"), _file(ctx, "SW_2.jpg")]},
    )
    assert rec.data["site"] == "NR"


def test_update_fills_a_blank_field_when_the_file_arrives(ctx: AppContext, recordings):
    rec = ctx.record_svc.add("study", "recording", {})
    assert rec.data.get("take") is None
    updated = ctx.record_svc.update(
        str(rec.id), {"audio": _file(ctx, "20240315_093000_t7.wav")}
    )
    assert updated.data["take"] == 7
    assert updated.data["name"] == "20240315_093000_t7"


def test_update_keeps_a_value_already_there(ctx: AppContext, recordings):
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "a_t1.wav"), "take": 9}
    )
    updated = ctx.record_svc.update(
        str(rec.id), {"audio": _file(ctx, "a_t2.wav"), "take": 9}
    )
    assert updated.data["take"] == 9


def test_a_datetime_is_read_in_the_collection_timezone(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study", timezone="America/Chicago")
    make_schema("recording", fields=[("audio", "file")])
    ctx.schema_svc.add_field(
        "recording", "start", "datetime", restrictions=_rule("audio", "YYYYMMDD_HHmmSS")
    )
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "20240315_093000.wav")}
    )
    assert rec.data["start"] == "2024-03-15T14:30:00+00:00"


def test_the_file_may_be_on_the_record_above(
    ctx: AppContext, make_schema, make_collection
):
    """A rule on a child schema reading a file field inherited from the
    parent: the file is on the parent record, so that is where it is read."""
    make_collection("study")
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter")
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    parent = ctx.record_svc.add(
        "study", "encounter", {"track": _file(ctx, "T12_20240315.gpx")}
    )
    child = ctx.record_svc.add("study", "sighting", {}, parent_record_id=str(parent.id))
    assert child.data["trip"] == "T12"
    # And on update, where the parent is fetched only because it is needed.
    updated = ctx.record_svc.update(str(child.id), {})
    assert updated.data["trip"] == "T12"


def test_a_rule_on_the_parent_schema_is_not_applied_to_child_records(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("encounter", fields=[("track", "file")])
    ctx.schema_svc.add_field(
        "encounter", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    make_schema("sighting", parent="encounter")
    parent = ctx.record_svc.add(
        "study", "encounter", {"track": _file(ctx, "T12_20240315.gpx")}
    )
    assert parent.data["trip"] == "T12"
    child = ctx.record_svc.add("study", "sighting", {}, parent_record_id=str(parent.id))
    assert "trip" not in child.data


# ---------------------------------------------------------------------------
# the rule on the schema
# ---------------------------------------------------------------------------


def test_the_rule_is_accepted_on_the_types_a_name_can_fill(
    ctx: AppContext, make_schema
):
    make_schema("doc", fields=[("attachment", "file")])
    for dtype, pattern in (
        ("string", "(.+)"),
        ("integer", r"(\d+)"),
        ("float", r"([\d.]+)"),
        ("date", "YYYY-MM-DD"),
        ("datetime", "YYYYMMDD_HHmmSS"),
    ):
        field = ctx.schema_svc.add_field(
            "doc", f"f_{dtype}", dtype, restrictions=_rule("attachment", pattern)
        )
        assert field.restrictions["from_filename"]["pattern"] == pattern


def test_the_rule_is_not_a_key_of_other_types(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file")])
    with pytest.raises(ValidationError, match="Unknown restriction"):
        ctx.schema_svc.add_field(
            "doc", "flag", "boolean", restrictions=_rule("attachment", "(.+)")
        )


@pytest.mark.parametrize(
    "value",
    [
        "attachment",
        {"field": "attachment"},
        {"field": "attachment", "pattern": ""},
        {"field": "attachment", "pattern": "(.+)", "extra": 1},
    ],
)
def test_a_malformed_rule_is_refused(ctx: AppContext, make_schema, value):
    make_schema("doc", fields=[("attachment", "file")])
    with pytest.raises(ValidationError, match="from_filename"):
        ctx.schema_svc.add_field(
            "doc", "name", "string", restrictions={"from_filename": value}
        )


def test_the_file_field_must_exist_and_be_a_file(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file"), ("notes", "string")])
    with pytest.raises(ValidationError, match="no field 'missing'"):
        ctx.schema_svc.add_field(
            "doc", "name", "string", restrictions=_rule("missing", "(.+)")
        )
    with pytest.raises(ValidationError, match="not a file field"):
        ctx.schema_svc.add_field(
            "doc", "name", "string", restrictions=_rule("notes", "(.+)")
        )


def test_the_pattern_must_compile_for_the_type(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file")])
    with pytest.raises(ValidationError, match="regular expression"):
        ctx.schema_svc.add_field(
            "doc", "name", "string", restrictions=_rule("attachment", "(")
        )
    with pytest.raises(ValidationError, match="YYYY MM DD"):
        ctx.schema_svc.add_field(
            "doc", "when", "date", restrictions=_rule("attachment", "HHmmSS")
        )


def test_the_file_field_may_be_inherited(ctx: AppContext, make_schema):
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter")
    field = ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    assert field.restrictions["from_filename"]["field"] == "track"


def test_update_field_checks_the_rule_too(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file"), ("name", "string")])
    with pytest.raises(ValidationError, match="no field 'missing'"):
        ctx.schema_svc.update_field(
            "doc", "name", restrictions=_rule("missing", "(.+)")
        )
    updated = ctx.schema_svc.update_field(
        "doc", "name", restrictions=_rule("attachment", "(.+)")
    )
    assert updated.restrictions == _rule("attachment", "(.+)")


def test_renaming_the_file_field_renames_it_in_the_rule(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file")])
    ctx.schema_svc.add_field(
        "doc", "name", "string", restrictions=_rule("attachment", "(.+)")
    )
    ctx.schema_svc.update_field("doc", "attachment", new_name="scan")
    name = next(f for f in ctx.schema_svc.get("doc").fields if f.name == "name")
    assert name.restrictions == _rule("scan", "(.+)")


def test_renaming_an_inherited_file_field_follows_into_the_child(
    ctx: AppContext, make_schema
):
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter")
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    ctx.schema_svc.update_field("encounter", "track", new_name="gps")
    trip = next(f for f in ctx.schema_svc.get("sighting").fields if f.name == "trip")
    assert trip.restrictions["from_filename"]["field"] == "gps"


def test_a_shadowing_own_field_is_left_alone(ctx: AppContext, make_schema):
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter", fields=[("track", "file")])
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    ctx.schema_svc.update_field("encounter", "track", new_name="gps")
    trip = next(f for f in ctx.schema_svc.get("sighting").fields if f.name == "trip")
    assert trip.restrictions["from_filename"]["field"] == "track"


def test_deleting_the_file_field_drops_the_rule(ctx: AppContext, make_schema):
    make_schema("doc", fields=[("attachment", "file")])
    ctx.schema_svc.add_field(
        "doc",
        "name",
        "string",
        restrictions={**_rule("attachment", "(.+)"), "max_length": 20},
    )
    ctx.schema_svc.delete_field("doc", "attachment")
    name = next(f for f in ctx.schema_svc.get("doc").fields if f.name == "name")
    assert name.restrictions == {"max_length": 20}


def test_the_descriptor_is_served(client):
    body = client.get("/api/schemas/field-types").json()
    by_type = {t["type"]: t for t in body["types"]}
    for dtype in ("string", "integer", "float", "date", "datetime"):
        keys = {r["key"]: r for r in by_type[dtype]["restrictions"]}
        assert keys["from_filename"]["control"] == "from_filename"
    assert "from_filename" not in {r["key"] for r in by_type["boolean"]["restrictions"]}
