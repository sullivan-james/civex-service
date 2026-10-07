"""Clean-up by age: deleted items, change history, workflow runs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from civex.config import RetentionConfig
from civex.context import AppContext
from civex.db.models import (
    AuditBatch,
    AuditLog,
    Record,
    StepExecution,
    WorkflowJob,
)
from civex.domain.dtos import RetentionCutoffs
from civex.repositories.local.job_repo import LocalWorkflowJobRepository
from civex.services.retention_service import RetentionService

TOMORROW = lambda: datetime.now(timezone.utc) + timedelta(days=1)  # noqa: E731
LAST_YEAR = lambda: datetime.now(timezone.utc) - timedelta(days=365)  # noqa: E731


def service(ctx: AppContext, protect_unsynced: bool = False, **retention):
    return RetentionService(
        ctx.record_svc,
        ctx.dataset_svc,
        ctx.schema_svc,
        ctx.audit_svc,
        LocalWorkflowJobRepository(ctx._session),
        RetentionConfig(**retention),
        protect_unsynced,
    )


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("label", "string")], parent="encounter")
    make_collection("humpback")
    enc = make_record("humpback", "encounter", {"site": "S"})
    recs = [
        make_record(
            "humpback", "recording", {"label": f"R{i}"}, parent_record_id=str(enc.id)
        )
        for i in range(3)
    ]
    return {"enc": enc, "recs": recs}


# --- settings ---------------------------------------------------------------


def test_by_default_nothing_has_a_cutoff_and_nothing_is_removed(ctx, survey):
    ctx.record_svc.delete(str(survey["enc"].id))
    ctx.commit()
    svc = service(ctx)
    assert svc.settings_cutoffs() == RetentionCutoffs()
    report = svc.run(svc.settings_cutoffs(), dry_run=False)
    assert not report.anything
    assert len(ctx.record_svc.list_deleted()) == 4


def test_settings_become_cutoffs_only_for_what_is_switched_on(ctx):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    off = service(ctx, purge_after_days=30, auto_purge_deleted=False, audit_days=90)
    cut = off.settings_cutoffs(now)
    assert cut.deleted_before is None  # a window alone deletes nothing
    assert cut.audit_before == now - timedelta(days=90)
    assert cut.runs_before is None
    on = service(ctx, purge_after_days=30, auto_purge_deleted=True, run_days=7)
    cut = on.settings_cutoffs(now)
    assert cut.deleted_before == now - timedelta(days=30)
    assert cut.runs_before == now - timedelta(days=7)


# --- deleted items ----------------------------------------------------------


def test_a_dry_run_counts_and_a_run_removes_deleted_items_for_good(ctx, survey):
    ctx.record_svc.delete(str(survey["enc"].id))  # the tree
    ctx.commit()
    svc = service(ctx)

    preview = svc.run(RetentionCutoffs(deleted_before=TOMORROW()))
    assert (preview.dry_run, preview.deleted_records) == (True, 4)
    assert len(ctx.record_svc.list_deleted()) == 4  # nothing happened

    report = svc.run(RetentionCutoffs(deleted_before=TOMORROW()), dry_run=False)
    ctx.commit()
    assert report.deleted_records == 4
    assert ctx.record_svc.list_deleted() == []
    # They are gone as records, but their history says what happened to them.
    gone, _ = ctx.history_svc.events(
        where={"and": [{"field": "now", "op": "eq", "value": "gone"}]}, limit=100
    )
    assert gone


def test_only_what_was_deleted_before_the_cutoff_is_removed(ctx, survey):
    ctx.record_svc.delete(str(survey["enc"].id))
    ctx.commit()
    report = service(ctx).run(
        RetentionCutoffs(deleted_before=LAST_YEAR()), dry_run=False
    )
    assert not report.anything
    assert len(ctx.record_svc.list_deleted()) == 4


def test_a_deleted_collection_goes_with_its_records_and_without_a_line_each(
    ctx, survey
):
    ctx.dataset_svc.delete("humpback")
    ctx.commit()
    report = service(ctx).run(
        RetentionCutoffs(deleted_before=TOMORROW()), dry_run=False
    )
    ctx.commit()
    assert (report.deleted_collections, report.deleted_records) == (1, 4)
    assert ctx.dataset_svc.list_deleted() == []
    assert ctx.record_svc.list_deleted() == []
    purges, _ = ctx.history_svc.events(
        where={"and": [{"field": "change", "op": "eq", "value": "purge"}]}, limit=100
    )
    # One purge for the collection; its records were not logged one by one.
    assert sum(e.count for e in purges) == 1


def test_a_deleted_schema_is_removed_unless_it_cannot_be(ctx, survey):
    ctx.schema_svc.delete("recording")
    ctx.commit()
    report = service(ctx).run(
        RetentionCutoffs(deleted_before=TOMORROW()), dry_run=False
    )
    ctx.commit()
    assert report.deleted_schemas == 1 and not report.skipped
    assert ctx.schema_svc.list_deleted() == []


def test_a_deleted_parent_with_a_child_that_stays_is_kept(ctx, survey):
    ctx.record_svc.delete(str(survey["enc"].id))
    ctx.commit()
    # One child is live again by some other route; its parent must not be cut away.
    ctx._session.execute(
        update(Record).where(Record.id == survey["recs"][0].id).values(deleted_at=None)
    )
    ctx.commit()
    purgeable = {rid for rid, _, _ in ctx.record_svc.purgeable_deleted(TOMORROW())}
    assert survey["enc"].id not in purgeable
    assert survey["recs"][0].id not in purgeable
    assert {survey["recs"][1].id, survey["recs"][2].id} <= purgeable
    service(ctx).run(RetentionCutoffs(deleted_before=TOMORROW()), dry_run=False)
    ctx.commit()
    assert {r.id for r in ctx.record_svc.list_deleted()} == {survey["enc"].id}


# --- change history ---------------------------------------------------------


def test_history_before_the_cutoff_is_removed_but_not_what_can_still_be_restored(
    ctx, survey
):
    ctx.record_svc.delete(str(survey["recs"][0].id))  # restorable
    ctx.commit()
    svc = service(ctx)
    preview = svc.run(RetentionCutoffs(audit_before=TOMORROW()))
    assert preview.audit_entries > 0 and preview.audit_kept_restorable == 2

    report = svc.run(RetentionCutoffs(audit_before=TOMORROW()), dry_run=False)
    ctx.commit()
    left = ctx.history_svc.page(entity_id=survey["recs"][0].id, limit=50)
    assert {e.action for e in left} == {"create", "delete"}  # all it has, kept
    # A live record keeps its creation (and latest change) however old.
    live = ctx.history_svc.page(entity_id=survey["recs"][1].id, limit=50)
    assert [e.action for e in live] == ["create"]
    assert report.audit_entries > 0

    # Once it is gone for good, its history is no longer held back.
    ctx.record_svc.purge(str(survey["recs"][0].id))
    ctx.commit()
    svc.run(RetentionCutoffs(audit_before=TOMORROW()), dry_run=False)
    ctx.commit()
    assert ctx.history_svc.page(entity_id=survey["recs"][0].id, limit=50) == []


def test_a_batch_with_nothing_left_is_removed_too(ctx, survey, make_record):
    enc = survey["enc"]
    with ctx.history_svc.batch("import", "x.csv"):
        ctx.record_svc.update(str(enc.id), {"site": "a"})
    ctx.record_svc.update(str(enc.id), {"site": "b"})  # its latest, kept
    ctx.commit()
    assert ctx._session.query(AuditBatch).count() == 1
    report = service(ctx).run(RetentionCutoffs(audit_before=TOMORROW()), dry_run=False)
    ctx.commit()
    assert report.audit_batches == 1
    assert ctx._session.query(AuditBatch).count() == 0


def test_a_live_record_keeps_its_creation_and_latest_change_however_old(
    ctx, survey
):
    """Pruning by age once left a live record with no history at all: nothing
    said where it came from, or how it came to be where it was."""
    rec = survey["recs"][2]
    for label in ("a", "b", "c"):
        ctx.record_svc.update(str(rec.id), {"label": label})
    ctx.commit()
    svc = service(ctx)
    preview = svc.run(RetentionCutoffs(audit_before=TOMORROW()))
    assert preview.audit_kept_first_and_last > 0

    svc.run(RetentionCutoffs(audit_before=TOMORROW()), dry_run=False)
    ctx.commit()
    left = ctx.history_svc.page(entity_id=rec.id, limit=50)  # newest first
    assert [e.action for e in left] == ["update", "create"]
    assert left[0].changes[0]["after"] == "c"  # the latest, not an older one


def test_with_a_remote_history_not_yet_synced_is_kept(ctx, survey):
    ctx.commit()
    svc = service(ctx, protect_unsynced=True)
    report = svc.run(RetentionCutoffs(audit_before=TOMORROW()), dry_run=False)
    assert report.audit_entries == 0 and report.audit_kept_unsynced > 0

    # Once the authority has acknowledged the entries they can go.
    ctx._session.query(AuditLog).update({"sync_state": "synced"})
    ctx.commit()
    assert svc.run(RetentionCutoffs(audit_before=TOMORROW())).audit_entries > 0


# --- workflow runs ----------------------------------------------------------


def test_finished_runs_and_their_step_logs_are_removed_but_never_a_pending_one(
    ctx, survey
):
    record = ctx.record_svc.find("humpback", "encounter")[0]
    done = ctx.job_svc.enqueue_manual("noop", record)
    waiting = ctx.job_svc.enqueue_manual("noop", record)
    ctx.commit()
    ctx.job_svc.mark_completed(
        done.id,
        step_executions=[
            {
                "step_id": "a",
                "plugin": "civex.noop",
                "status": "completed",
                "duration_seconds": 0.1,
            }
        ],
    )
    ctx.commit()

    svc = service(ctx)
    preview = svc.run(RetentionCutoffs(runs_before=TOMORROW()))
    assert (preview.runs, preview.run_steps) == (1, 1)
    assert svc.run(RetentionCutoffs(runs_before=LAST_YEAR())).runs == 0

    svc.run(RetentionCutoffs(runs_before=TOMORROW()), dry_run=False)
    ctx.commit()
    remaining = {j.id for j in ctx._session.query(WorkflowJob)}
    assert remaining == {waiting.id}
    assert ctx._session.query(StepExecution).count() == 0
