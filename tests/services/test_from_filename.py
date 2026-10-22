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


def _file(ctx: AppContext, name: str, content: bytes | None = None) -> dict:
    """A stored file called `name`; its bytes are the name unless given."""
    return ctx.file_svc.store_bytes(content or name.encode(), name).to_dict()


def _rule(field: str, pattern) -> dict:
    return {"from_filename": {"field": field, "pattern": pattern}}


def _restrictions(ctx: AppContext, schema: str, field: str) -> dict:
    return next(
        f for f in ctx.schema_svc.get(schema).fields if f.name == field
    ).restrictions


@pytest.fixture()
def recordings(ctx: AppContext, make_schema, make_collection):
    """A recording with an `audio` file and fields read from its name."""
    make_collection("study")
    make_schema("recording", fields=[("audio", "file")])
    for name, dtype, pattern in (
        ("name", "string", r"^(.+)\.wav$"),
        ("take", "integer", r"_t(\d+)"),
        ("start", "datetime", "YYYYMMDD[-_]HHmmSS"),
    ):
        ctx.schema_svc.add_field(
            "recording", name, dtype, restrictions=_rule("audio", pattern)
        )
    ctx.commit()


@pytest.fixture()
def nested(ctx: AppContext, make_schema, make_collection):
    """A sighting inside an encounter, reading the encounter's `track` file."""
    make_collection("study")
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter")
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )


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
        # Named groups: the parts in any order, any width.
        (
            r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})",
            "date",
            "scan_15.03.2024.pdf",
            "2024-03-15",
        ),
        (
            r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})T(?P<hour>\d{1,2})h",
            "datetime",
            "20240315T9h.csv",
            "2024-03-15T09:00:00",
        ),
        # Several patterns: the first that matches wins.
        (
            ["DDMMYYYY_HHmmSS", "YYYY-MM-DD"],
            "datetime",
            "15032024_093000.csv",
            "2024-03-15T09:30:00",
        ),
        (
            ["DDMMYYYY_HHmmSS", "YYYY-MM-DD"],
            "datetime",
            "site_2024-03-15.csv",
            "2024-03-15T00:00:00",
        ),
        ([r"take_(\d+)", r"sel_(\d+)"], "integer", "sel_12.txt", 12),
        ([r"take_(\d+)", r"sel_(\d+)"], "integer", "other.txt", None),
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
        (r"(?P<year>\d{4})", "date", "needs month, day"),
        (
            r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})(?P<week>\d)",
            "date",
            r"unknown group\(s\) week",
        ),
        (r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})", "date", None),
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


# ---------------------------------------------------------------------------
# deriving on add and update
# ---------------------------------------------------------------------------


def test_blank_fields_are_filled_in_the_same_save(ctx: AppContext, recordings):
    """One save, one history entry, and the values read from the file's name
    are in it: nothing runs afterwards to fill the fields."""
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "20240315_093000_t3.wav")}
    )
    assert rec.data["name"] == "20240315_093000_t3"
    assert rec.data["take"] == 3
    assert rec.data["start"] == "2024-03-15T09:30:00+00:00"
    ctx.commit()
    entries = ctx.history_svc.page(entity_id=rec.id)
    assert [e.action for e in entries] == ["create"]
    take = next(f for f in ctx.schema_svc.get("recording").fields if f.name == "take")
    assert entries[0].new_data["data"][str(take.id)] == 3


def test_a_typed_value_is_kept_and_a_name_that_fits_nothing_leaves_a_blank(
    ctx: AppContext, recordings
):
    typed = ctx.record_svc.add(
        "study",
        "recording",
        {"audio": _file(ctx, "20240315_093000_t3.wav"), "name": "dawn chorus"},
    )
    assert typed.data["name"] == "dawn chorus"
    assert typed.data["take"] == 3
    unfit = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "x.wav"), "take": 4}
    )
    assert unfit.data["name"] == "x"
    assert unfit.data["take"] == 4
    assert unfit.data.get("start") is None
    assert ctx.record_svc.add("study", "recording", {}).data.get("name") is None


def test_the_derived_value_is_checked_like_a_typed_one(
    ctx: AppContext, make_schema, make_collection
):
    """Not the type: refused naming the field. Outside its rules: refused.
    Part of a unique key: it counts."""
    make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    take = ctx.schema_svc.add_field(
        "doc",
        "take",
        "integer",
        restrictions={**_rule("attachment", r"take_(\w+)"), "max": 10},
    )
    with pytest.raises(FieldValueError, match="'take'.*take_ab.pdf") as e:
        ctx.record_svc.add("study", "doc", {"attachment": _file(ctx, "take_ab.pdf")})
    assert e.value.path == f"data.{take.id}"
    with pytest.raises(ValidationError, match="exceeds maximum"):
        ctx.record_svc.add("study", "doc", {"attachment": _file(ctx, "take_42.pdf")})
    ctx.schema_svc.set_unique_keys("doc", [["take"]])
    ctx.record_svc.add("study", "doc", {"attachment": _file(ctx, "take_1.pdf")})
    with pytest.raises(DuplicateRecordError):
        ctx.record_svc.add(
            "study", "doc", {"attachment": _file(ctx, "take_1.pdf", b"x")}
        )


def test_a_file_list_gives_its_first_file_and_is_read_again_when_it_changes(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("doc", fields=[("photos", "file_list")])
    ctx.schema_svc.add_field(
        "doc", "site", "string", restrictions=_rule("photos", r"^([A-Z]+)_")
    )
    rec = ctx.record_svc.add(
        "study", "doc", {"photos": [_file(ctx, "NR_1.jpg"), _file(ctx, "SW_2.jpg")]}
    )
    assert rec.data["site"] == "NR"
    rec = ctx.record_svc.update(str(rec.id), {**rec.data, "site": "Nairn"})
    # Another file after the first: the first is the same, the edit stays.
    appended = ctx.record_svc.update(
        str(rec.id),
        {**rec.data, "photos": [*rec.data["photos"], _file(ctx, "X_3.jpg")]},
    )
    assert appended.data["site"] == "Nairn"
    replaced = ctx.record_svc.update(
        str(rec.id),
        {**appended.data, "photos": [_file(ctx, "AB_4.jpg"), *appended.data["photos"]]},
    )
    assert replaced.data["site"] == "AB"


def test_a_new_file_reads_the_fields_again_but_a_value_given_with_it_is_kept(
    ctx: AppContext, recordings
):
    rec = ctx.record_svc.add("study", "recording", {})
    arrived = ctx.record_svc.update(str(rec.id), {"audio": _file(ctx, "a_t1.wav")})
    assert arrived.data["take"] == 1
    # The value belonged to the old file: a different file replaces it,
    # unless the person set it in the same save.
    with_value = ctx.record_svc.update(
        str(rec.id), {**arrived.data, "audio": _file(ctx, "b_t2.wav"), "take": 9}
    )
    assert with_value.data["take"] == 9
    assert with_value.data["name"] == "b_t2"
    again = ctx.record_svc.update(
        str(rec.id), {**with_value.data, "audio": _file(ctx, "c_t3.wav")}
    )
    assert again.data["take"] == 3


def test_a_hand_edit_stays_until_a_file_that_fits_replaces_the_file(
    ctx: AppContext, recordings
):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    edited = ctx.record_svc.update(str(rec.id), {**rec.data, "take": 9})
    assert edited.data["take"] == 9
    same = ctx.record_svc.update(str(rec.id), dict(edited.data))
    assert same.data["take"] == 9
    # A new file that fits no pattern leaves the value; removing the file too.
    unfit = ctx.record_svc.update(
        str(rec.id), {**same.data, "audio": _file(ctx, "other.wav")}
    )
    assert unfit.data["take"] == 9
    assert unfit.data["name"] == "other"
    gone = ctx.record_svc.update(str(rec.id), {**unfit.data, "audio": None})
    assert gone.data["take"] == 9
    fits = ctx.record_svc.update(
        str(rec.id), {**gone.data, "audio": _file(ctx, "a_t3.wav")}
    )
    assert fits.data["take"] == 3


@pytest.mark.parametrize(
    "first,second",
    [
        (("a_t1.wav", b"same bytes"), ("a_t5.wav", b"same bytes")),  # renamed
        (("a_t1.wav", b"first take"), ("a_t5.wav", b"re-recorded")),  # replaced
    ],
)
def test_a_file_is_new_when_its_name_or_its_content_changes(
    ctx: AppContext, recordings, first, second
):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, *first)})
    edited = ctx.record_svc.update(str(rec.id), {**rec.data, "take": 9})
    changed = ctx.record_svc.update(
        str(rec.id), {**edited.data, "audio": _file(ctx, *second)}
    )
    assert changed.data["take"] == 5


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


def test_the_file_may_be_on_the_record_above(ctx: AppContext, nested):
    """A child reading a file field inherited from the parent: the file is on
    the parent record. The child doesn't hold it, so on the child's saves it
    counts as unchanged (a hand edit stays) and a parent's save never
    reaches into its children; blank again, it is read from the parent's
    file as it is now."""
    parent = ctx.record_svc.add(
        "study", "encounter", {"track": _file(ctx, "T12_20240315.gpx")}
    )
    child = ctx.record_svc.add("study", "sighting", {}, parent_record_id=str(parent.id))
    assert child.data["trip"] == "T12"
    assert ctx.record_svc.update(str(child.id), {}).data["trip"] == "T12"
    edited = ctx.record_svc.update(str(child.id), {"trip": "edited"})
    ctx.record_svc.update(str(parent.id), {"track": _file(ctx, "T99_20240316.gpx")})
    assert ctx.record_svc.get(str(child.id)).data["trip"] == edited.data["trip"]
    assert ctx.record_svc.update(str(child.id), {"trip": None}).data["trip"] == "T99"


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
    child = ctx.record_svc.add("study", "sighting", {}, parent_record_id=str(parent.id))
    assert parent.data["trip"] == "T12"
    assert "trip" not in child.data


# ---------------------------------------------------------------------------
# the rule on the schema
# ---------------------------------------------------------------------------


def test_the_rule_is_accepted_on_the_types_a_name_can_fill_and_no_other(
    ctx: AppContext, make_schema
):
    make_schema("doc", fields=[("attachment", "file")])
    for dtype, pattern in (
        ("string", "(.+)"),
        ("integer", r"(\d+)"),
        ("float", r"([\d.]+)"),
        ("date", r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})"),
        ("datetime", ["DDMMYYYY_HHmmSS", "YYYY-MM-DD"]),
    ):
        field = ctx.schema_svc.add_field(
            "doc", f"f_{dtype}", dtype, restrictions=_rule("attachment", pattern)
        )
        assert field.restrictions["from_filename"]["pattern"] == pattern
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
        {"field": "attachment", "pattern": []},
        {"field": "attachment", "pattern": ["(.+)", ""]},
        {"field": "attachment", "pattern": ["(.+)", 3]},
        {"field": "attachment", "pattern": ["(.+)", "("]},
    ],
)
def test_a_malformed_rule_is_refused(ctx: AppContext, make_schema, value):
    make_schema("doc", fields=[("attachment", "file")])
    with pytest.raises(ValidationError, match="from_filename"):
        ctx.schema_svc.add_field(
            "doc", "name", "string", restrictions={"from_filename": value}
        )


def test_the_file_field_must_be_a_file_field_and_the_pattern_fit_the_type(
    ctx: AppContext, make_schema
):
    make_schema("doc", fields=[("attachment", "file"), ("notes", "string")])
    for field, pattern, message in (
        ("missing", "(.+)", "no field 'missing'"),
        ("notes", "(.+)", "not a file field"),
        ("attachment", "(", "regular expression"),
    ):
        with pytest.raises(ValidationError, match=message):
            ctx.schema_svc.add_field(
                "doc", "name", "string", restrictions=_rule(field, pattern)
            )
    with pytest.raises(ValidationError, match="YYYY MM DD"):
        ctx.schema_svc.add_field(
            "doc", "when", "date", restrictions=_rule("attachment", "HHmmSS")
        )
    # update_field checks the same.
    with pytest.raises(ValidationError, match="no field 'missing'"):
        ctx.schema_svc.update_field(
            "doc", "notes", restrictions=_rule("missing", "(.+)")
        )


def test_renaming_or_deleting_the_file_field_follows_into_the_rule(
    ctx: AppContext, make_schema
):
    make_schema("doc", fields=[("attachment", "file")])
    ctx.schema_svc.add_field(
        "doc",
        "name",
        "string",
        restrictions={**_rule("attachment", "(.+)"), "max_length": 20},
    )
    ctx.schema_svc.update_field("doc", "attachment", new_name="scan")
    assert _restrictions(ctx, "doc", "name") == {
        **_rule("scan", "(.+)"),
        "max_length": 20,
    }
    ctx.schema_svc.delete_field("doc", "scan")
    assert _restrictions(ctx, "doc", "name") == {"max_length": 20}


def test_an_inherited_file_field_may_be_read_and_its_rename_follows_into_the_child(
    ctx: AppContext, nested
):
    ctx.schema_svc.update_field("encounter", "track", new_name="gps")
    assert _restrictions(ctx, "sighting", "trip")["from_filename"]["field"] == "gps"


def test_a_shadowing_own_field_is_left_alone(ctx: AppContext, make_schema):
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter", fields=[("track", "file")])
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    ctx.schema_svc.update_field("encounter", "track", new_name="gps")
    assert _restrictions(ctx, "sighting", "trip")["from_filename"]["field"] == "track"


# ---------------------------------------------------------------------------
# served
# ---------------------------------------------------------------------------


def test_the_descriptor_is_served(client):
    body = client.get("/api/schemas/field-types").json()
    by_type = {t["type"]: t for t in body["types"]}
    for dtype in ("string", "integer", "float", "date", "datetime"):
        keys = {r["key"]: r for r in by_type[dtype]["restrictions"]}
        assert keys["from_filename"]["control"] == "from_filename"
    assert "from_filename" not in {r["key"] for r in by_type["boolean"]["restrictions"]}


def test_the_preview_tries_the_patterns_without_saving_anything(client):
    """The field editor's live preview: the server is the one implementation
    of the patterns, so the frontend holds no copy of them."""
    url = "/api/schemas/from-filename/preview"
    body = client.post(
        url, json={"filename": "", "patterns": ["HHmmSS", "YYYY-MM-DD"], "kind": "date"}
    ).json()
    assert body["problems"][0].startswith("a date pattern needs the tokens")
    assert body["problems"][1] is None and body["value"] is None
    body = client.post(
        url,
        json={
            "filename": "site_2024-03-15.csv",
            "patterns": ["YYYY-MM-DD"],
            "kind": "date",
        },
    ).json()
    assert body == {"problems": [None], "value": "2024-03-15", "error": None}
    body = client.post(
        url,
        json={
            "filename": "take_ab.wav",
            "patterns": [r"take_(\w+)"],
            "kind": "integer",
        },
    ).json()
    assert body["value"] is None and "not a whole number" in body["error"]
