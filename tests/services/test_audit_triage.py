"""Finding lost or changed data: what happened under a record, in a collection,
to a value or a file -- and where the thing is now."""

from __future__ import annotations

import pytest

from civex.context import AppContext


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("label", "string")], parent="encounter")
    make_collection("humpback")
    make_collection("other")
    e1 = make_record("humpback", "encounter", {"site": "Stellwagen"})
    e2 = make_record("humpback", "encounter", {"site": "Georges"})
    r1 = make_record(
        "humpback", "recording", {"label": "R1"}, parent_record_id=str(e1.id)
    )
    r2 = make_record(
        "humpback", "recording", {"label": "R2"}, parent_record_id=str(e1.id)
    )
    elsewhere = make_record(
        "humpback", "recording", {"label": "R3"}, parent_record_id=str(e2.id)
    )
    return {"e1": e1, "e2": e2, "r1": r1, "r2": r2, "elsewhere": elsewhere}


def leaf(field: str, value, op: str = "eq") -> dict:
    return {"field": field, "op": op, "value": value}


def _where(*conditions: dict) -> dict:
    return {"and": list(conditions)}


def _within(ctx: AppContext, record, action: str | None = None):
    conditions = [leaf("under", str(record.id))]
    if action:
        conditions.append(leaf("change", action))
    events, _ = ctx.history_svc.events(where=_where(*conditions), limit=100)
    return events


def test_a_missing_recording_shows_under_its_encounter_as_deleted_and_restorable(
    ctx: AppContext, survey
):
    ctx.record_svc.delete(str(survey["r1"].id))
    ctx.commit()

    events = _within(ctx, survey["e1"], action="delete")
    assert len(events) == 1
    entry = events[0].entry
    assert entry.entity_id == survey["r1"].id
    assert entry.now["status"] == "deleted"
    assert (entry.now["collection"], entry.now["name"]) == ("humpback", "R1")
    # What was in it, to recognise it by.
    assert {c["field"]: c["before"] for c in entry.changes} == {"label": "R1"}


def test_the_encounters_view_leaves_out_other_encounters(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["elsewhere"].id))
    ctx.commit()
    assert _within(ctx, survey["e1"], action="delete") == []
    assert len(_within(ctx, survey["e2"], action="delete")) == 1


def test_a_purged_recording_is_still_found_and_said_to_be_gone(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["r2"].id))
    ctx.record_svc.purge(str(survey["r2"].id))
    ctx.commit()

    events = _within(ctx, survey["e1"], action="purge")
    assert len(events) == 1  # found through its snapshot naming the encounter
    assert events[0].entry.entity_id == survey["r2"].id
    assert events[0].entry.now == {
        "kind": "record",
        "status": "gone",
        "schema_name": "recording",
    }


def test_a_whole_encounter_delete_shows_as_one_event_with_the_missing_recordings(
    ctx: AppContext, survey
):
    ctx.record_svc.delete(str(survey["e1"].id))
    ctx.commit()
    events = _within(ctx, survey["e1"], action="delete")
    assert len(events) == 1 and events[0].batch is not None
    assert events[0].count == 3  # the encounter and both recordings


def test_what_changed_under_an_encounter_includes_edits(ctx: AppContext, survey):
    ctx.record_svc.update(str(survey["r1"].id), {"label": "R1b"})
    ctx.commit()
    events = _within(ctx, survey["e1"], action="update")
    assert [e.entry.entity_id for e in events] == [survey["r1"].id]
    assert events[0].entry.now["status"] == "live"


# --- a value or file that moved on ---------------------------------------


@pytest.fixture()
def files(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("selection", fields=[("table", "file"), ("note", "string")])
    make_collection("Test Datas")
    make_collection("elsewhere")
    old = {"sha256": "a" * 64, "filename": "selection-017.txt", "size": 10}
    new = {"sha256": "b" * 64, "filename": "selection-018.txt", "size": 11}
    here = make_record("Test Datas", "selection", {"table": old, "note": "keep"})
    other = make_record("elsewhere", "selection", {"table": old, "note": "keep"})
    return {"here": here, "other": other, "old": old, "new": new}


def test_a_file_name_finds_where_it_was_and_when_it_was_replaced(
    ctx: AppContext, files
):
    ctx.record_svc.update(
        str(files["here"].id), {"table": files["new"], "note": "keep"}
    )
    ctx.commit()

    events, _ = ctx.history_svc.events(
        where=_where(leaf("collection", "Test Datas")),
        search="selection-017.txt",
        limit=50,
    )
    updates = [e.entry for e in events if e.entry.action == "update"]
    assert [u.entity_id for u in updates] == [files["here"].id]
    change = updates[0].changes[0]
    assert change["dtype"] == "file"
    assert (change["before"]["filename"], change["after"]["filename"]) == (
        "selection-017.txt",
        "selection-018.txt",
    )
    assert updates[0].now["collection"] == "Test Datas"


def test_the_collection_filter_keeps_other_collections_out(ctx: AppContext, files):
    in_test, _ = ctx.history_svc.events(
        where=_where(leaf("collection", "Test Datas")), limit=50
    )
    in_other, _ = ctx.history_svc.events(
        where=_where(leaf("collection", "elsewhere")), limit=50
    )
    test_ids = {e.entry.entity_id for e in in_test if e.entry}
    other_ids = {e.entry.entity_id for e in in_other if e.entry}
    assert files["here"].id in test_ids and files["other"].id not in test_ids
    assert files["other"].id in other_ids and files["here"].id not in other_ids


def test_a_collection_filter_also_finds_a_deleted_records_history(
    ctx: AppContext, files
):
    ctx.record_svc.delete(str(files["here"].id))
    ctx.commit()
    events, _ = ctx.history_svc.events(
        where=_where(leaf("collection", "Test Datas"), leaf("change", "delete"))
    )
    assert [e.entry.now["status"] for e in events] == ["deleted"]


def test_the_collection_can_be_given_by_id_and_unknown_ones_are_refused(
    ctx: AppContext, files
):
    from civex.domain.exceptions import NotFoundError

    cid = str(ctx.dataset_svc.get("Test Datas").id)
    events, total = ctx.history_svc.events(
        where=_where(leaf("collection", cid)), limit=50
    )
    assert total >= 1
    with pytest.raises(NotFoundError):
        ctx.history_svc.events(where=_where(leaf("collection", "nope")))


def test_now_filters_by_where_the_record_is_now(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["r1"].id))
    ctx.record_svc.delete(str(survey["r2"].id))
    ctx.record_svc.restore(str(survey["r2"].id))
    ctx.record_svc.delete(str(survey["elsewhere"].id))
    ctx.record_svc.purge(str(survey["elsewhere"].id))
    ctx.commit()

    def entities(state: str, op: str = "eq") -> set:
        events, _ = ctx.history_svc.events(
            where=_where(leaf("now", state, op)), limit=100
        )
        return {e.entry.entity_id for e in events if e.entry}

    assert entities("deleted") == {survey["r1"].id}
    assert entities("gone") == {survey["elsewhere"].id}
    assert survey["r2"].id in entities("live") and survey["r1"].id not in entities(
        "live"
    )
    # Not live: deleted or gone, together.
    assert entities("live", "ne") >= {survey["r1"].id, survey["elsewhere"].id}


def test_a_filter_can_combine_with_or_and_not_equal(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["r1"].id))
    ctx.record_svc.update(str(survey["r2"].id), {"label": "R2b"})
    ctx.commit()
    either = {
        "and": [
            leaf("under", str(survey["e1"].id)),
            {"or": [leaf("change", "delete"), leaf("change", "update")]},
        ]
    }
    events, _ = ctx.history_svc.events(where=either, limit=100)
    assert {e.entry.action for e in events} == {"delete", "update"}
    not_created = _where(
        leaf("under", str(survey["e1"].id)), leaf("change", "create", "ne")
    )
    events, _ = ctx.history_svc.events(where=not_created, limit=100)
    assert "create" not in {e.entry.action for e in events}


def test_a_bad_filter_is_refused_with_a_reason(ctx: AppContext):
    from civex.domain.exceptions import ValidationError

    with pytest.raises(ValidationError, match="Unknown history field"):
        ctx.history_svc.events(where=_where(leaf("nonsense", "x")))
    with pytest.raises(ValidationError, match="doesn't apply"):
        ctx.history_svc.events(where=_where(leaf("kind", "x", "gt")))
    with pytest.raises(ValidationError, match="valid JSON"):
        ctx.history_svc.events(where="{nope")


def test_where_now_names_the_schema_even_for_a_record_gone_for_good(
    ctx: AppContext, survey
):
    live = ctx.history_svc.page(entity_id=survey["r1"].id)[0]
    assert live.now["schema_name"] == "recording" and live.now["name"] == "R1"

    ctx.record_svc.delete(str(survey["r2"].id))
    ctx.record_svc.purge(str(survey["r2"].id))
    ctx.commit()
    gone = ctx.history_svc.page(entity_id=survey["r2"].id)[0]
    assert gone.now == {"kind": "record", "status": "gone", "schema_name": "recording"}


def test_schema_filter_finds_the_schema_its_fields_and_its_records_only(
    ctx: AppContext, survey
):
    ctx.record_svc.update(str(survey["r1"].id), {"label": "R1b"})
    ctx.commit()

    def about(*names: str, op: str = "eq") -> list:
        value = names[0] if len(names) == 1 and op == "eq" else list(names)
        events, _ = ctx.history_svc.events(
            where=_where(leaf("schema", value, "in" if len(names) > 1 else op)),
            limit=200,
        )
        return [e.entry for e in events if e.entry]

    recording = about("recording")
    kinds = {e.entity_type for e in recording}
    assert kinds == {"schema", "field", "record"}  # itself, its field, its records
    records = [e for e in recording if e.entity_type == "record"]
    assert {e.entity_id for e in records} == {
        survey["r1"].id,
        survey["r2"].id,
        survey["elsewhere"].id,
    }  # recordings only: not the encounters they sit under
    assert all(e.entity_id not in {survey["e1"].id, survey["e2"].id} for e in recording)

    # Either schema, and everything but one.
    both = about("recording", "encounter")
    assert {survey["e1"].id, survey["r1"].id} <= {e.entity_id for e in both}
    not_recording = about("recording", op="ne")
    assert survey["r1"].id not in {e.entity_id for e in not_recording}
    assert survey["e1"].id in {e.entity_id for e in not_recording}


def test_schema_filter_works_for_a_deleted_schema_and_refuses_an_unknown_one(
    ctx: AppContext, survey
):
    from civex.domain.exceptions import NotFoundError

    ctx.schema_svc.delete("recording")
    ctx.commit()
    events, _ = ctx.history_svc.events(
        where=_where(leaf("schema", "recording")), limit=200
    )
    assert any(e.entry.entity_type == "record" for e in events)
    with pytest.raises(NotFoundError):
        ctx.history_svc.events(where=_where(leaf("schema", "nope")))


def test_a_deleted_collection_or_schema_says_it_is_deleted_and_how_to_restore_it(
    ctx: AppContext, survey, make_collection, make_schema
):
    make_schema("spare")
    ctx.dataset_svc.delete("other")
    ctx.schema_svc.delete("spare")
    ctx.commit()

    def entry_for(entity_type: str, action: str):
        events, _ = ctx.history_svc.events(
            where=_where(leaf("kind", entity_type), leaf("change", action)), limit=50
        )
        return events[0].entry

    collection = entry_for("dataset", "delete")
    assert collection.now["kind"] == "collection"
    assert (collection.now["status"], collection.now["ref"]) == ("deleted", "other")
    schema = entry_for("schema", "delete")
    assert (schema.now["kind"], schema.now["status"], schema.now["ref"]) == (
        "schema",
        "deleted",
        "spare",
    )

    # The Now filter sees them too, beside deleted records.
    events, _ = ctx.history_svc.events(
        where=_where(leaf("now", "deleted"), leaf("change", "delete")), limit=50
    )
    assert {e.entry.entity_type for e in events} == {"dataset", "schema"}

    ctx.dataset_svc.restore("other")
    ctx.commit()
    assert entry_for("dataset", "delete").now["status"] == "live"
    ctx.dataset_svc.delete("other")
    ctx.dataset_svc.purge("other")
    ctx.commit()
    assert entry_for("dataset", "purge").now == {"kind": "collection", "status": "gone"}
