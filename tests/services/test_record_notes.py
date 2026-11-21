"""Notes on records and their threads (`civex.domain.notes`): notes written,
replied to, edited, resolved and deleted, who may, what history says, what a
record's delete, restore and purge do to its notes, and finding records with
open threads."""

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


def _listed(ctx: AppContext, tree) -> set[str]:
    page = ctx.record_svc.query_records(
        RecordQuery(dataset="survey", schema="sample", filter_tree=tree)
    )
    return {r.data["site"] for r in page}


def test_a_filter_on_open_notes_takes_true_or_false(ctx: AppContext, study):
    with pytest.raises(ValidationError):
        _listed(ctx, {"field": "@open_notes", "op": "eq", "value": "yes"})
    with pytest.raises(ValidationError):
        _listed(ctx, {"field": "@open_notes", "op": "ne", "value": True})


def test_a_list_shows_open_threads_and_the_latest_ones_first_line(
    ctx: AppContext, study
):
    a, b, c = study
    ctx.note_svc.add(str(a.id), "older thread")
    latest = ctx.note_svc.add(str(a.id), "  depth looks off\nsee the log  ")
    ctx.note_svc.reply(str(latest.id), "a reply is not a thread")
    done = ctx.note_svc.add(str(b.id), "resolved")
    ctx.note_svc.resolve(str(done.id))
    ctx.commit()
    listed = {
        r.data["site"]: (r.open_notes, r.latest_note)
        for r in ctx.record_svc.query_records(
            RecordQuery(dataset="survey", schema="sample"),
            columns=["@open_notes"],
        )
    }
    assert listed == {"a": (2, "depth looks off"), "b": (0, None), "c": (0, None)}


def test_listing_open_notes_costs_the_same_however_many(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("sample", fields=[("site", "string")])
    make_collection("few")
    make_collection("many")
    for name, n in (("few", 2), ("many", 20)):
        for i in range(n):
            record = make_record(name, "sample", {"site": f"{name}{i}"})
            for j in range(3):
                note = ctx.note_svc.add(str(record.id), f"thread {j}")
                ctx.note_svc.reply(str(note.id), "reply")
    ctx.commit()

    def cost(name: str) -> int:
        with _statements(ctx) as seen:
            ctx.record_svc.query_records(
                RecordQuery(dataset=name, schema="sample"), columns=["@open_notes"]
            )
        return len(seen)

    assert cost("few") == cost("many")


# --- notes


def test_notes_are_written_resolved_edited_and_deleted(ctx: AppContext, study):
    a = study[0]
    note = ctx.note_svc.add(str(a.id), "  value looks off, re-check calibration ")
    ctx.commit()
    assert note.body == "value looks off, re-check calibration"
    assert note.author == ctx.note_svc._actor
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


# --- threads


def test_replies_are_listed_under_the_note_they_answer(ctx: AppContext, study):
    a = study[0]
    first = ctx.note_svc.add(str(a.id), "depth looks off")
    second = ctx.note_svc.add(str(a.id), "site name misspelt")
    reply = ctx.note_svc.reply(str(first.id), "it was the sensor, fixed")
    # A reply to a reply joins the same thread.
    again = ctx.note_svc.reply(str(reply.id)[:8], "thanks")
    ctx.commit()
    assert reply.thread_id == first.id and again.thread_id == first.id
    threads = ctx.note_svc.notes(str(a.id))
    assert [(t.body, [r.body for r in t.replies]) for t in threads] == [
        ("depth looks off", ["it was the sensor, fixed", "thanks"]),
        ("site name misspelt", []),
    ]
    assert second.replies == []
    # Two threads open, however many replies.
    assert ctx.record_svc.get(str(a.id)).open_notes == 2
    counted = ctx.note_svc.open_notes(RecordQuery(dataset="survey", schema="sample"))
    assert (counted.notes, counted.records) == (2, 1)


def test_a_thread_is_resolved_whole_and_a_reply_opens_it_again(ctx: AppContext, study):
    a = study[0]
    first = ctx.note_svc.add(str(a.id), "depth looks off")
    reply = ctx.note_svc.reply(str(first.id), "fixed")
    # Resolving from a reply resolves the thread.
    resolved = ctx.note_svc.resolve(str(reply.id))
    ctx.commit()
    assert resolved.id == first.id and resolved.resolved_at is not None
    assert ctx.note_svc.notes(str(a.id), include_resolved=False) == []
    assert _listed(ctx, {"field": "@open_notes", "op": "eq", "value": True}) == set()

    ctx.note_svc.reply(str(first.id), "no, still off")
    ctx.commit()
    (thread,) = ctx.note_svc.notes(str(a.id), include_resolved=False)
    assert thread.resolved_at is None and len(thread.replies) == 2
    # The reply and the reopening are one action.
    ops = {
        e.op_id
        for e in ctx._session.query(AuditLog)
        .filter(AuditLog.entity_type == "note")
        .order_by(AuditLog.local_seq.desc())
        .limit(2)
    }
    assert len(ops) == 1 and None not in ops


def test_replies_are_deleted_alone_or_hidden_with_their_thread(ctx: AppContext, study):
    a = study[0]
    first = ctx.note_svc.add(str(a.id), "depth looks off")
    gone = ctx.note_svc.reply(str(first.id), "typo")
    kept = ctx.note_svc.reply(str(first.id), "fixed")
    ctx.note_svc.delete(str(gone.id))
    ctx.commit()
    assert [r.body for r in ctx.note_svc.notes(str(a.id))[0].replies] == ["fixed"]

    ctx.note_svc.delete(str(first.id))
    ctx.commit()
    assert ctx.note_svc.notes(str(a.id)) == []
    with pytest.raises(NotFoundError):
        ctx.note_svc.reply(str(kept.id), "hello?")
    with pytest.raises(ValidationError):
        ctx.note_svc.restore(str(gone.id))

    ctx.note_svc.restore(str(first.id))
    ctx.commit()
    # The thread's replies come back with it; the one deleted by itself stays.
    assert [r.body for r in ctx.note_svc.notes(str(a.id))[0].replies] == ["fixed"]
    ctx.note_svc.restore(str(gone.id))
    ctx.commit()
    assert [r.body for r in ctx.note_svc.notes(str(a.id))[0].replies] == [
        "typo",
        "fixed",
    ]


def test_only_its_author_changes_a_reply(ctx: AppContext, study):
    first = ctx.note_svc.add(str(study[0].id), "depth looks off")
    reply = ctx.note_svc.reply(str(first.id), "fixd")
    ctx.note_svc.edit(str(reply.id), "fixed")
    ctx.commit()
    ctx.note_svc._actor = "someone else"
    with pytest.raises(NotAllowedError):
        ctx.note_svc.edit(str(reply.id), "not fixed")
    # Anyone who may write may reply.
    ctx.note_svc.reply(str(reply.id), "agreed")


def test_listing_threads_costs_the_same_however_many(ctx: AppContext, study):
    a, b, _ = study
    for record, threads in ((a, 2), (b, 12)):
        for i in range(threads):
            note = ctx.note_svc.add(str(record.id), f"note {i}")
            for j in range(3):
                ctx.note_svc.reply(str(note.id), f"reply {j}")
    ctx.commit()

    def cost(record) -> int:
        with _statements(ctx) as seen:
            ctx.note_svc.notes(str(record.id))
        return len(seen)

    assert cost(a) == cost(b)


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


def test_who_may_write_notes(as_someone):
    as_, mine, here, there = as_someone
    reader = as_(Permissions.of(p.READ))
    try:
        assert reader.note_svc.notes(str(here.id)) == []
        with pytest.raises(NotAllowedError):
            reader.note_svc.add(str(here.id), "hello")
    finally:
        reader.close()
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        note = writer.note_svc.add(str(here.id), "hello")
        with pytest.raises(NotAllowedError):
            writer.note_svc.add(str(there.id), "hello")
        writer.commit()
    finally:
        writer.close()
    other = as_(Permissions.of(p.READ, p.WRITE_RECORDS), actor="Someone Else")
    try:
        with pytest.raises(NotAllowedError):
            other.note_svc.edit(str(note.id), "changed")
        other.note_svc.resolve(str(note.id))
        other.note_svc.reply(str(note.id), "seen")
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
