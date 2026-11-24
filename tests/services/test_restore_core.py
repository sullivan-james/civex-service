"""The one core that applies record changes (`RecordService.apply_changes`):
a preview runs the checks the real run runs, `force` reaches it, a person
limited to some collections is held to them, and the history entries it writes
are the ones `log_change` writes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.db.models import AuditLog
from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project
from civex.repositories.local.audit_repo import LocalAuditRepository


def _batch_of(ctx: AppContext, kind: str):
    events, _ = ctx.history_svc.events(
        where={"and": [{"field": "how", "op": "eq", "value": kind}]}
    )
    return events[0].batch.id


# --- a preview asks what the real run asks ------------------------------------


@pytest.fixture()
def referenced(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("patient")
    make_schema("visit", fields=[("patient_ref", "reference")])
    make_collection("study")
    one = make_record("study", "patient", {})
    two = make_record("study", "patient", {})
    ctx.record_svc.delete_many([str(one.id), str(two.id)])
    ctx.commit()
    deleted = _batch_of(ctx, "delete")
    ctx.history_svc.revert_batch(deleted, dry_run=False)  # both are back
    ctx.commit()
    undo = _batch_of(ctx, "restore")
    visit = make_record("study", "visit", {"patient_ref": str(one.id)})
    return one, two, visit, undo


def test_a_refused_redo_is_refused_in_the_preview_too(ctx: AppContext, referenced):
    one, two, visit, undo = referenced
    with pytest.raises(ValidationError, match="visit"):
        ctx.history_svc.revert_batch(undo)  # the preview
    with pytest.raises(ValidationError, match="visit"):
        ctx.history_svc.revert_batch(undo, dry_run=False)
    assert ctx.record_svc.get(str(one.id)).deleted_at is None
    assert ctx.record_svc.get(str(two.id)).deleted_at is None


def test_force_reaches_the_redo_and_a_preview_writes_nothing(
    ctx: AppContext, referenced
):
    one, two, visit, undo = referenced
    preview = ctx.history_svc.revert_batch(undo, force=True)
    assert (preview.applied, preview.left) == (2, 0)
    # The preview cleared nothing and deleted nothing.
    assert ctx.record_svc.get(str(visit.id)).data["patient_ref"] == str(one.id)
    assert ctx.record_svc.get(str(one.id)).deleted_at is None
    done = ctx.history_svc.revert_batch(undo, force=True, dry_run=False)
    ctx.commit()
    assert (done.applied, done.left) == (2, 0)
    assert ctx.record_svc.get(str(visit.id)).data.get("patient_ref") is None


# --- a person limited to some collections -------------------------------------


@pytest.fixture()
def study(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.schema_svc.add_field("sample", "label", "string")
    mine = owner.dataset_svc.create("mine")
    theirs = owner.dataset_svc.create("theirs")
    made = {
        "mine": [
            owner.record_svc.add("mine", "sample", {"label": f"m{i}"}) for i in range(3)
        ],
        "theirs": [
            owner.record_svc.add("theirs", "sample", {"label": f"t{i}"})
            for i in range(3)
        ],
    }
    owner.commit()

    def as_(perms: Permissions) -> AppContext:
        return build_context(
            Project(
                config=load_config_at(root),
                config_store=FileConfigStore(root),
                actor="Dr Example",
                permissions=perms,
            )
        )

    yield owner, as_, mine, theirs, made
    owner.close()


def test_a_limited_writer_undoes_where_they_may_write_and_is_refused_elsewhere(study):
    owner, as_, mine, theirs, made = study
    everything = [str(r.id) for r in [*made["mine"], *made["theirs"]]]
    owner.record_svc.delete_many(everything)
    owner.commit()
    both = _batch_of(owner, "delete")

    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        # A set that reaches a collection they may not write in is refused as a
        # whole, by the preview as by the undo, before anything is written.
        with pytest.raises(NotAllowedError):
            writer.history_svc.revert_batch(both)
        with pytest.raises(NotAllowedError):
            writer.history_svc.revert_batch(both, dry_run=False)
    finally:
        writer.close()
    assert owner.record_svc.find("mine", "sample") == []
    assert owner.record_svc.find("theirs", "sample") == []

    # What the owner deletes in the writer's collection alone they may undo.
    owner.record_svc.restore_set([str(r.id) for r in made["mine"]])
    owner.commit()
    owner.record_svc.delete_many([str(r.id) for r in made["mine"]])
    owner.commit()
    again = _batch_of(owner, "delete")
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS, collections=[mine.id]))
    try:
        assert writer.history_svc.revert_batch(again).applied == 3
        assert writer.history_svc.revert_batch(again, dry_run=False).applied == 3
        writer.commit()
    finally:
        writer.close()
    assert {r.id for r in owner.record_svc.find("mine", "sample")} == {
        r.id for r in made["mine"]
    }


def test_a_reader_is_refused_by_the_preview_as_by_the_undo(study):
    owner, as_, mine, theirs, made = study
    owner.record_svc.delete_many([str(r.id) for r in made["mine"]])
    owner.commit()
    batch = _batch_of(owner, "delete")
    reader = as_(Permissions.of(p.READ))
    try:
        with pytest.raises(NotAllowedError):
            reader.history_svc.revert_batch(batch)
        with pytest.raises(NotAllowedError):
            reader.history_svc.revert_batch(batch, dry_run=False)
    finally:
        reader.close()
    assert owner.record_svc.find("mine", "sample") == []


# --- the entries it writes are the entries log_change writes -------------------


def test_a_bulk_entry_equals_a_log_change_entry_column_by_column(ctx: AppContext):
    session = ctx._session
    repo = LocalAuditRepository(session, actor="A\tB", device_id=uuid.uuid4())
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    op, one, two = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def snap(rid, deleted):
        return {
            "id": str(rid),
            "dataset_id": str(rid),
            "schema_id": str(rid),
            "parent_record_id": None,
            "deleted_at": deleted,
        }

    with repo.batch("restore", "x"):
        # Pending in the session when the bulk writer is called: it must keep
        # the lower write number.
        repo.log_change(
            "restore", "record", one, snap(one, "t"), snap(one, None), when, op
        )
        repo.log_changes(
            "restore", "record", [(two, snap(two, "t"), snap(two, None))], when, op
        )
        three, four = uuid.uuid4(), uuid.uuid4()
        repo.log_change("delete", "record", three, snap(three, "t"), None, when, op)
        repo.log_changes("delete", "record", [(four, snap(four, "t"), None)], when, op)
    session.flush()

    columns = [
        AuditLog.action,
        AuditLog.entity_type,
        AuditLog.old_data.is_(None),
        AuditLog.new_data.is_(None),
        AuditLog.delta.is_(None),
        AuditLog.format,
        AuditLog.op_id,
        AuditLog.batch_id,
        AuditLog.actor,
        AuditLog.device,
        AuditLog.device_id,
        AuditLog.apply_state,
        AuditLog.sync_state,
        AuditLog.hub_seq,
        AuditLog.timestamp,
    ]

    def row(rid):
        return session.execute(select(*columns).where(AuditLog.entity_id == rid)).one()

    assert tuple(row(one)) == tuple(row(two))
    first, second = (
        session.execute(
            select(
                AuditLog.local_seq, AuditLog.hlc, AuditLog.old_data, AuditLog.delta
            ).where(AuditLog.entity_id == rid)
        ).one()
        for rid in (one, two)
    )
    assert first.local_seq < second.local_seq
    assert first.hlc is not None and second.hlc is not None and first.hlc < second.hlc
    assert (first.old_data, first.delta) == (second.old_data, second.delta)
    # A delete's missing new side is the JSON null in both, never SQL NULL.
    assert tuple(row(three)) == tuple(row(four))
    assert tuple(row(three))[2:5] == (False, False, False)
