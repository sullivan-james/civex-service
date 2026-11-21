"""Review status and notes on records (`civex.domain.review`): setting a status
on a selection, notes written, edited, resolved and deleted, who may, what
history says, what a record's delete, restore and purge do to its notes, and
filtering a list by either."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.db.models import AuditLog, RecordNote
from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery
from civex.project import Project, scaffold_project


@pytest.fixture()
def study(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    return [make_record("survey", "sample", {"site": s}) for s in ("a", "b", "c")]


def _ids(records) -> list[str]:
    return [str(r.id) for r in records]


def _listed(ctx: AppContext, tree) -> set[str]:
    page = ctx.record_svc.query_records(
        RecordQuery(dataset="survey", schema="sample", filter_tree=tree)
    )
    return {r.data["site"] for r in page}


# --- review status


def test_marking_records_needs_a_check_and_then_checked(ctx: AppContext, study):
    a, b, c = study
    before = ctx.record_svc.get(str(a.id)).updated_at
    result = ctx.record_svc.set_review("needs_check", ids=_ids([a, b]))
    ctx.commit()
    assert (result.records, result.changed, result.unchanged) == (2, 2, 0)
    got = ctx.record_svc.get(str(a.id))
    assert got.review["status"] == "needs_check"
    assert got.review["by"] == ctx.record_svc.actor
    # A review is not an edit of the record's values.
    assert got.updated_at == before

    again = ctx.record_svc.set_review("needs_check", ids=_ids([a, b, c]))
    assert (again.changed, again.unchanged) == (1, 2)
    ctx.commit()

    cleared = ctx.record_svc.set_review("none", ids=_ids([c]))
    ctx.commit()
    assert cleared.changed == 1
    assert ctx.record_svc.get(str(c.id)).review is None


def test_a_review_by_query_marks_what_the_list_shows(ctx: AppContext, study):
    query = RecordQuery(
        dataset="survey",
        schema="sample",
        filter_tree={"field": "site", "op": "in", "value": ["a", "b"]},
    )
    planned = ctx.record_svc.set_review("checked", query=query, dry_run=True)
    assert planned.changed == 2
    assert _listed(ctx, {"field": "@review", "op": "eq", "value": "checked"}) == set()
    ctx.record_svc.set_review("checked", query=query)
    ctx.commit()
    assert _listed(ctx, {"field": "@review", "op": "eq", "value": "checked"}) == {
        "a",
        "b",
    }
    assert _listed(ctx, {"field": "@review", "op": "eq", "value": "none"}) == {"c"}
    assert _listed(ctx, {"field": "@review", "op": "ne", "value": "checked"}) == {"c"}
    assert _listed(
        ctx, {"field": "@review", "op": "in", "value": ["none", "checked"]}
    ) == {"a", "b", "c"}


def test_an_unknown_status_or_operator_is_refused(ctx: AppContext, study):
    with pytest.raises(ValidationError):
        ctx.record_svc.set_review("looked_at", ids=_ids(study))
    with pytest.raises(ValidationError):
        _listed(ctx, {"field": "@review", "op": "gt", "value": "checked"})
    with pytest.raises(ValidationError):
        _listed(ctx, {"field": "@review", "op": "eq", "value": "maybe"})
    with pytest.raises(ValidationError):
        _listed(ctx, {"field": "@open_notes", "op": "eq", "value": "yes"})


def test_a_review_is_one_event_in_history_and_reads_as_words(ctx: AppContext, study):
    ctx.record_svc.set_review("needs_check", ids=_ids(study))
    ctx.commit()
    entries = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "record", AuditLog.action == "update")
        .all()
    )
    assert len(entries) == 3
    assert len({e.batch_id for e in entries}) == 1 and entries[0].batch_id
    assert ctx.audit_svc.get_batch(entries[0].batch_id).kind == "review"
    one = ctx.history_svc.get(entries[0].id)
    (change,) = one.changes
    assert (change["label"], change["before"], change["after"]) == (
        "Review",
        "Not reviewed",
        "Needs a check",
    )


def test_marking_many_records_costs_the_same_however_many(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("survey")
    few = [str(make_record("survey", "sample", {"site": "x"}).id) for _ in range(3)]
    many = [str(make_record("survey", "sample", {"site": "y"}).id) for _ in range(30)]

    def cost(ids: list[str]) -> int:
        with _statements(ctx) as seen:
            ctx.record_svc.set_review("checked", ids=ids)
        ctx.commit()
        return len([s for s in seen if not s.lstrip().upper().startswith("INSERT")])

    assert cost(few) == cost(many)


# --- notes


def test_notes_are_written_resolved_edited_and_deleted(ctx: AppContext, study):
    a = study[0]
    note = ctx.note_svc.add(str(a.id), "  value looks off, re-check calibration ")
    ctx.commit()
    assert note.body == "value looks off, re-check calibration"
    assert note.author == ctx.record_svc.actor
    assert ctx.record_svc.get(str(a.id)).open_notes == 1

    ctx.note_svc.edit(str(note.id)[:8], "re-check the calibration")
    resolved = ctx.note_svc.resolve(str(note.id))
    ctx.commit()
    assert resolved.resolved_at is not None and resolved.edited_at is not None
    assert ctx.note_svc.notes(str(a.id), include_resolved=False) == []
    assert ctx.record_svc.get(str(a.id)).open_notes == 0

    ctx.note_svc.resolve(str(note.id), resolved=False)
    ctx.note_svc.delete(str(note.id))
    ctx.commit()
    assert ctx.note_svc.notes(str(a.id)) == []
    ctx.note_svc.restore(str(note.id))
    ctx.commit()
    assert [n.body for n in ctx.note_svc.notes(str(a.id))] == [
        "re-check the calibration"
    ]
    actions = [
        e.action
        for e in ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "note")
        .order_by(AuditLog.local_seq)
    ]
    assert actions == ["create", "update", "update", "update", "delete", "restore"]


def test_a_note_must_say_something_and_not_too_much(ctx: AppContext, study):
    with pytest.raises(ValidationError):
        ctx.note_svc.add(str(study[0].id), "   ")
    with pytest.raises(ValidationError):
        ctx.note_svc.add(str(study[0].id), "x" * 4001)
    with pytest.raises(NotFoundError):
        ctx.note_svc.add("ffffffff", "hello")


def test_open_notes_count_and_filter(ctx: AppContext, study):
    a, b, _ = study
    ctx.note_svc.add(str(a.id), "one")
    ctx.note_svc.add(str(a.id), "two")
    done = ctx.note_svc.add(str(b.id), "three")
    ctx.note_svc.resolve(str(done.id))
    ctx.commit()
    counted = ctx.note_svc.open_notes(RecordQuery(dataset="survey", schema="sample"))
    assert (counted.notes, counted.records) == (2, 1)
    assert _listed(ctx, {"field": "@open_notes", "op": "eq", "value": True}) == {"a"}
    assert _listed(ctx, {"field": "@open_notes", "op": "eq", "value": False}) == {
        "b",
        "c",
    }


def test_a_deleted_record_hides_its_notes_and_brings_them_back(ctx: AppContext, study):
    a = study[0]
    note = ctx.note_svc.add(str(a.id), "look again")
    ctx.commit()
    ctx.record_svc.delete(str(a.id))
    ctx.commit()
    with pytest.raises(NotFoundError):
        ctx.note_svc.notes(str(a.id))
    with pytest.raises(NotFoundError):
        ctx.note_svc.resolve(str(note.id))
    ctx.record_svc.restore(str(a.id))
    ctx.commit()
    assert [n.id for n in ctx.note_svc.notes(str(a.id))] == [note.id]


def test_a_record_purged_takes_its_notes_and_their_history(ctx: AppContext, study):
    a = study[0]
    note = ctx.note_svc.add(str(a.id), "look again")
    ctx.note_svc.resolve(str(note.id))
    ctx.commit()
    ctx.record_svc.delete(str(a.id))
    ctx.record_svc.purge(str(a.id))
    ctx.commit()
    assert ctx._session.get(RecordNote, note.id) is None
    assert (
        ctx._session.query(AuditLog).filter(AuditLog.entity_id == note.id).count() == 0
    )


def test_a_collection_purged_takes_its_records_notes(ctx: AppContext, study):
    note = ctx.note_svc.add(str(study[1].id), "look again")
    ctx.commit()
    ctx.dataset_svc.delete("survey")
    ctx.dataset_svc.purge("survey")
    ctx.commit()
    assert ctx._session.get(RecordNote, note.id) is None
    assert (
        ctx._session.query(AuditLog).filter(AuditLog.entity_id == note.id).count() == 0
    )


# --- who may


@pytest.fixture()
def as_someone(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.schema_svc.add_field("sample", "site", "string")
    mine = owner.dataset_svc.create("mine")
    owner.dataset_svc.create("theirs")
    here = owner.record_svc.add("mine", "sample", {"site": "x"})
    there = owner.record_svc.add("theirs", "sample", {"site": "y"})
    owner.commit()

    def as_(perms: Permissions, actor: str = "Dr Example") -> AppContext:
        return build_context(
            Project(
                config=load_config_at(root),
                config_store=FileConfigStore(root),
                actor=actor,
                permissions=perms,
            )
        )

    yield as_, mine, here, there
    owner.close()


def test_who_may_write_notes_and_set_reviews(as_someone):
    as_, mine, here, there = as_someone
    reader = as_(Permissions.of(p.READ))
    try:
        assert reader.note_svc.notes(str(here.id)) == []
        with pytest.raises(NotAllowedError):
            reader.note_svc.add(str(here.id), "hello")
        with pytest.raises(NotAllowedError):
            reader.record_svc.set_review("checked", ids=[str(here.id)])
    finally:
        reader.close()
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        note = writer.note_svc.add(str(here.id), "hello")
        writer.record_svc.set_review("checked", ids=[str(here.id)])
        with pytest.raises(NotAllowedError):
            writer.note_svc.add(str(there.id), "hello")
        with pytest.raises(NotAllowedError):
            writer.record_svc.set_review("checked", ids=[str(here.id), str(there.id)])
        writer.commit()
    finally:
        writer.close()
    other = as_(Permissions.of(p.READ, p.WRITE_RECORDS), actor="Someone Else")
    try:
        with pytest.raises(NotAllowedError):
            other.note_svc.edit(str(note.id), "changed")
        other.note_svc.resolve(str(note.id))
        other.commit()
    finally:
        other.close()


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
