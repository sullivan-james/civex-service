"""History entries stored as only what changed (`format` 2) read exactly like the
whole snapshots they replace: the same changes, the same revert, found by the
same filters and searches. Each test makes real entries, reads them, turns them
into deltas in the database the way the conversion will, and reads them again."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from civex.context import AppContext
from civex.db.models import AuditLog
from civex.domain.audit_diff import identity, make_delta


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    return _survey(ctx, make_schema, make_collection, make_record)


@pytest.fixture()
def old_survey(ctx: AppContext, make_schema, make_collection, make_record, monkeypatch):
    """The same, with history written as v1.2.0 wrote it: whole snapshots."""
    import civex.repositories.local.audit_repo as audit_repo

    with monkeypatch.context() as patched:  # (not undo(): that undoes the chdir)
        patched.setattr(audit_repo, "stored_form", lambda o, n: (o, n, None, 1))
        made = _survey(ctx, make_schema, make_collection, make_record)
    return made


def _survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string"), ("depth", "float")])
    make_schema(
        "recording",
        fields=[("label", "string"), ("count", "integer")],
        parent="encounter",
    )
    make_collection("humpback")
    e1 = make_record("humpback", "encounter", {"site": "Stellwagen", "depth": 10.0})
    r1 = make_record(
        "humpback",
        "recording",
        {"label": "R1", "count": 1},
        parent_record_id=str(e1.id),
    )
    ctx.record_svc.update(str(r1.id), {"label": "R1 (fixed)", "count": 2})
    ctx.record_svc.update(str(e1.id), {"site": "Georges", "depth": 10.0})
    ctx.commit()
    return {"e1": e1, "r1": r1}


def _as_deltas(ctx: AppContext) -> int:
    """Store every whole-snapshot update entry as a delta, as the conversion will."""
    rows = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.action == "update", AuditLog.format == 1)
        .all()
    )
    for row in rows:
        row.delta = make_delta(row.old_data, row.new_data)
        row.new_data = identity(row.new_data)
        row.old_data = None
        row.format = 2
    ctx.commit()
    return len(rows)


def _read(ctx: AppContext) -> dict:
    entries = ctx.history_svc.page(limit=200)
    return {
        e.id: (e.action, e.entity_type, e.entity_id, e.changes, e.now) for e in entries
    }


def test_converted_entries_show_the_same_changes(ctx: AppContext, old_survey):
    before = _read(ctx)
    assert _as_deltas(ctx) >= 2
    assert _read(ctx) == before


def test_a_converted_update_reverts_the_same_way(ctx: AppContext, old_survey):
    update = next(
        e
        for e in ctx.history_svc.page(entity_id=old_survey["r1"].id, limit=50)
        if e.action == "update"
    )
    plan = ctx.history_svc.plan_revert(update.id)
    _as_deltas(ctx)
    assert ctx.history_svc.plan_revert(update.id) == plan

    ctx.history_svc.revert(update.id)
    ctx.commit()
    assert ctx.record_svc.get(str(old_survey["r1"].id)).data["label"] == "R1"


@pytest.mark.parametrize(
    "where",
    [
        lambda s: {"and": [{"field": "under", "op": "eq", "value": str(s["e1"].id)}]},
        lambda s: {"and": [{"field": "collection", "op": "eq", "value": "humpback"}]},
        lambda s: {"and": [{"field": "schema", "op": "eq", "value": "recording"}]},
    ],
)
def test_converted_entries_are_found_by_the_same_filters(
    ctx: AppContext, old_survey, where
):
    def found():
        events, total = ctx.history_svc.events(where=where(old_survey), limit=100)
        return total, sorted(str(e.entry.id) for e in events if e.entry)

    before = found()
    assert before[0] > 0
    _as_deltas(ctx)
    assert found() == before


def test_a_value_only_in_what_changed_is_found_by_search(ctx: AppContext, old_survey):
    _, before = ctx.history_svc.events(search="Georges", limit=100)
    assert before >= 1
    _as_deltas(ctx)
    _, after = ctx.history_svc.events(search="Georges", limit=100)
    assert after == before


def test_changes_go_out_in_the_order_they_were_written_even_if_the_clock_stepped_back(
    ctx: AppContext,
):
    """The database numbers each entry as it is written. A clock stepping back
    (WSL after sleep) must not put a later change before an earlier one."""
    audit = ctx.audit_svc
    now = datetime.now(timezone.utc)
    first, second = uuid.uuid4(), uuid.uuid4()
    audit.log_change("create", "schema", first, None, {"id": str(first)}, now)
    audit.log_change(
        "create", "schema", second, None, {"id": str(second)}, now - timedelta(hours=1)
    )
    ctx.commit()

    rows = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_id.in_([first, second]))
        .all()
    )
    seq = {r.entity_id: r.local_seq for r in rows}
    assert seq[first] is not None and seq[second] > seq[first]
    order = [e.entity_id for e in ctx.sync_repo.pending_entries(1000)]
    assert order.index(first) < order.index(second)


def test_an_edit_is_stored_as_what_changed_and_a_create_or_delete_whole(
    ctx: AppContext, survey
):
    rows = {
        r.action: r
        for r in ctx._session.query(AuditLog)
        .filter(AuditLog.entity_id == survey["e1"].id)
        .all()
    }
    edit = rows["update"]
    site = next(f for f in ctx.schema_svc.get("encounter").fields if f.name == "site")
    assert edit.format == 2 and edit.old_data is None
    assert set(edit.delta) == {f"data.{site.id}", "updated_at"}
    assert edit.delta[f"data.{site.id}"] == {"before": "Stellwagen", "after": "Georges"}
    assert edit.new_data == identity(edit.new_data)  # identity only
    assert rows["create"].format == 1 and rows["create"].new_data["data"]

    ctx.record_svc.delete(str(survey["r1"].id))
    ctx.commit()
    gone = (
        ctx._session.query(AuditLog)
        .filter(AuditLog.entity_id == survey["r1"].id, AuditLog.action == "delete")
        .one()
    )
    assert gone.format == 1 and gone.old_data["data"]  # what was lost, once
