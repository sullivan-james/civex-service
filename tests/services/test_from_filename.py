"""A field filled from a file's name as the record is saved: the
`from_filename` restriction (`domain/filename_extract`, applied by
`RecordService._fill_from_filenames`, checked by `SchemaService`)."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from civex.context import AppContext
from civex.domain import filename_extract
from civex.domain.exceptions import (
    DuplicateRecordError,
    FieldValueError,
    ValidationError,
)


def _file(ctx: AppContext, name: str, content: bytes | None = None) -> dict:
    """A stored file called `name`; its bytes are the name unless given, so
    two names are two files."""
    return ctx.file_svc.store_bytes(content or name.encode(), name).to_dict()


def _rule(field: str, pattern: str) -> dict:
    return {"from_filename": {"field": field, "pattern": pattern}}


def _field_id(ctx: AppContext, schema: str, name: str) -> str:
    return str(next(f for f in ctx.schema_svc.get(schema).fields if f.name == name).id)


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


def test_the_derived_value_is_part_of_the_same_save(ctx: AppContext, recordings):
    """One save, one history entry, and the value read from the file's name
    is in it: nothing runs afterwards to fill the field."""
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "20240315_093000_t3.wav")}
    )
    ctx.commit()
    entries = ctx.history_svc.page(entity_id=rec.id)
    assert [e.action for e in entries] == ["create"]
    take = next(f for f in ctx.schema_svc.get("recording").fields if f.name == "take")
    assert entries[0].new_data["data"][str(take.id)] == 3


def test_a_typed_value_is_kept(ctx: AppContext, recordings):
    """A value given with the file is the person's, not an old file's: the
    file arriving doesn't discard it (the other fields are still filled)."""
    rec = ctx.record_svc.add(
        "study",
        "recording",
        {"audio": _file(ctx, "20240315_093000_t3.wav"), "name": "dawn chorus"},
    )
    assert rec.data["name"] == "dawn chorus"
    assert rec.data["take"] == 3


def test_a_name_the_pattern_does_not_fit_leaves_the_field_as_it_is(
    ctx: AppContext, recordings
):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "x.wav")})
    assert rec.data["name"] == "x"
    assert rec.data.get("take") is None
    assert rec.data.get("start") is None
    # A typed value stays too.
    typed = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "x.wav"), "take": 4}
    )
    assert typed.data["take"] == 4


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


def test_update_with_a_new_file_reads_the_fields_again(ctx: AppContext, recordings):
    """The value belonged to the old file: a different file replaces it,
    whether it was typed or derived."""
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "a_t1.wav"), "take": 9}
    )
    assert rec.data["take"] == 9
    updated = ctx.record_svc.update(
        str(rec.id), {**rec.data, "audio": _file(ctx, "b_t2.wav")}
    )
    assert updated.data["take"] == 2
    assert updated.data["name"] == "b_t2"


def test_update_keeps_a_hand_edit_while_the_file_is_the_same(
    ctx: AppContext, recordings
):
    """A hand edit is an override until the file changes."""
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    assert rec.data["take"] == 1
    edited = ctx.record_svc.update(str(rec.id), {**rec.data, "take": 9})
    assert edited.data["take"] == 9
    # Saved again with the same file and nothing typed: still the edit.
    again = ctx.record_svc.update(str(rec.id), dict(edited.data))
    assert again.data["take"] == 9
    # Until the file changes.
    replaced = ctx.record_svc.update(
        str(rec.id), {**again.data, "audio": _file(ctx, "a_t3.wav")}
    )
    assert replaced.data["take"] == 3


def test_a_value_given_with_the_new_file_is_kept(ctx: AppContext, recordings):
    """A value set in the same save as the new file is the person's, so the
    new file doesn't discard it (the fields left alone are read again)."""
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    updated = ctx.record_svc.update(
        str(rec.id), {**rec.data, "audio": _file(ctx, "b_t2.wav"), "take": 9}
    )
    assert updated.data["take"] == 9
    assert updated.data["name"] == "b_t2"


def test_the_same_bytes_under_a_new_name_are_a_new_file(ctx: AppContext, recordings):
    """The rule reads the name, so a file renamed is a file changed, even
    though its content (and so its hash) is the same."""
    rec = ctx.record_svc.add(
        "study", "recording", {"audio": _file(ctx, "a_t1.wav", b"same bytes")}
    )
    assert rec.data["take"] == 1
    renamed = ctx.record_svc.update(
        str(rec.id), {**rec.data, "audio": _file(ctx, "a_t5.wav", b"same bytes")}
    )
    assert renamed.data["take"] == 5


def test_the_same_name_with_new_content_is_a_new_file(ctx: AppContext, recordings):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    edited = ctx.record_svc.update(str(rec.id), {**rec.data, "take": 9})
    assert edited.data["take"] == 9
    replaced = ctx.record_svc.update(
        str(rec.id), {**edited.data, "audio": _file(ctx, "a_t1.wav", b"re-recorded")}
    )
    assert replaced.data["take"] == 1


def test_a_new_file_that_fits_no_pattern_leaves_the_value(ctx: AppContext, recordings):
    rec = ctx.record_svc.add("study", "recording", {"audio": _file(ctx, "a_t1.wav")})
    assert rec.data["take"] == 1
    updated = ctx.record_svc.update(
        str(rec.id), {**rec.data, "audio": _file(ctx, "other.wav")}
    )
    assert updated.data["take"] == 1
    assert updated.data["name"] == "other"
    # And removing the file blanks nothing.
    gone = ctx.record_svc.update(str(rec.id), {**updated.data, "audio": None})
    assert gone.data["take"] == 1


def test_a_file_list_is_read_again_only_when_its_first_file_changes(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("doc", fields=[("photos", "file_list")])
    ctx.schema_svc.add_field(
        "doc", "site", "string", restrictions=_rule("photos", r"^([A-Z]+)_")
    )
    rec = ctx.record_svc.add("study", "doc", {"photos": [_file(ctx, "NR_1.jpg")]})
    rec = ctx.record_svc.update(str(rec.id), {**rec.data, "site": "Nairn"})
    # Another file after the first: the first is the same, the edit stays.
    appended = ctx.record_svc.update(
        str(rec.id),
        {**rec.data, "photos": [*rec.data["photos"], _file(ctx, "SW_2.jpg")]},
    )
    assert appended.data["site"] == "Nairn"
    # The first file replaced: read again.
    replaced = ctx.record_svc.update(
        str(rec.id),
        {
            **appended.data,
            "photos": [_file(ctx, "AB_3.jpg"), *appended.data["photos"]],
        },
    )
    assert replaced.data["site"] == "AB"


def test_a_file_replaced_through_the_attach_route_overwrites_the_field(
    client: TestClient, ctx: AppContext, recordings
):
    """`PUT /records/{id}/files/{field}` saves the record through `patch`, so
    a replaced file re-reads the field in the same save: one `update` entry
    holds both the file and the value read from its name."""

    def attach(record_id: str, name: str, body: bytes):
        r = client.put(
            f"/api/records/{record_id}/files/audio?name={name}&size={len(body)}",
            content=body,
            headers={"content-length": str(len(body))},
        )
        assert r.status_code == 200, r.text
        return r.json()["data"]

    rec = ctx.record_svc.add("study", "recording", {})
    ctx.commit()
    first = attach(str(rec.id), "a_t1.wav", b"first take")
    assert first["take"] == 1
    second = attach(str(rec.id), "b_t2.wav", b"second take")
    assert second["take"] == 2
    assert second["name"] == "b_t2"

    entries = ctx.history_svc.page(entity_id=rec.id)
    assert sorted(e.action for e in entries) == ["create", "update", "update"]
    last = max((e for e in entries if e.action == "update"), key=lambda e: e.timestamp)
    delta = last.delta or {}
    audio = _field_id(ctx, "recording", "audio")
    take = _field_id(ctx, "recording", "take")
    assert delta[f"data.{audio}"]["after"]["filename"] == "b_t2.wav"
    assert delta[f"data.{take}"] == {"before": 1, "after": 2}


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


def test_a_child_field_is_filled_only_while_blank_from_the_record_above(
    ctx: AppContext, make_schema, make_collection
):
    """The child doesn't hold the parent's file, so on its saves that file
    counts as unchanged: a hand edit stays. And a parent's save never reaches
    into its children."""
    make_collection("study")
    make_schema("encounter", fields=[("track", "file")])
    make_schema("sighting", parent="encounter")
    ctx.schema_svc.add_field(
        "sighting", "trip", "string", restrictions=_rule("track", r"^(\w+)_")
    )
    parent = ctx.record_svc.add(
        "study", "encounter", {"track": _file(ctx, "T12_20240315.gpx")}
    )
    child = ctx.record_svc.add(
        "study", "sighting", {"trip": "typed"}, parent_record_id=str(parent.id)
    )
    assert child.data["trip"] == "typed"
    edited = ctx.record_svc.update(str(child.id), {"trip": "edited"})
    assert edited.data["trip"] == "edited"
    ctx.record_svc.update(str(parent.id), {"track": _file(ctx, "T99_20240316.gpx")})
    assert ctx.record_svc.get(str(child.id)).data["trip"] == "edited"
    # Blank again, it is read from the parent's file as it is now.
    cleared = ctx.record_svc.update(str(child.id), {"trip": None})
    assert cleared.data["trip"] == "T99"


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


def test_several_patterns_are_one_rule_tried_in_order(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("sample", fields=[("reading", "file")])
    ctx.schema_svc.add_field(
        "sample",
        "taken_at",
        "datetime",
        restrictions={
            "from_filename": {
                "field": "reading",
                "pattern": ["DDMMYYYY_HHmmSS", "YYYY-MM-DD"],
            }
        },
    )
    first = ctx.record_svc.add(
        "study", "sample", {"reading": _file(ctx, "15032024_093000.csv")}
    )
    second = ctx.record_svc.add(
        "study", "sample", {"reading": _file(ctx, "site_2024-03-16.csv")}
    )
    assert first.data["taken_at"] == "2024-03-15T09:30:00+00:00"
    assert second.data["taken_at"] == "2024-03-16T00:00:00+00:00"


def test_a_date_regex_with_named_groups_is_a_pattern(
    ctx: AppContext, make_schema, make_collection
):
    make_collection("study")
    make_schema("sample", fields=[("reading", "file")])
    ctx.schema_svc.add_field(
        "sample",
        "taken_on",
        "date",
        restrictions=_rule(
            "reading", r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})"
        ),
    )
    rec = ctx.record_svc.add(
        "study", "sample", {"reading": _file(ctx, "scan_15.03.2024.pdf")}
    )
    assert rec.data["taken_on"] == "2024-03-15"


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
