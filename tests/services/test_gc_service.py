"""GCService: mark-and-sweep over the content-addressed object store."""

from __future__ import annotations

import os
import time

from civex.context import AppContext


def _store(ctx: AppContext, content: bytes, name: str):
    return ctx.file_svc._store.put(content, name)


def test_referenced_object_survives_gc(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("doc", fields=[("attachments", "file_list")])
    make_collection("study")
    ref = _store(ctx, b"kept", "kept.txt")
    make_record("study", "doc", {"attachments": [ref.to_dict()]})

    report = ctx.gc_svc.run(dry_run=True, grace_days=0)
    assert report.deleted_count == 0
    assert report.referenced == 1
    assert ctx.file_svc._store.exists(ref.sha256)


def test_unreferenced_object_is_collected_when_applied(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("doc")
    make_collection("study")
    ref = _store(ctx, b"orphan", "orphan.txt")

    dry = ctx.gc_svc.run(dry_run=True, grace_days=0)
    assert dry.deleted_count == 1
    assert dry.deleted[0].sha256 == ref.sha256
    assert ctx.file_svc._store.exists(ref.sha256), "dry run must not delete"

    applied = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert applied.deleted_count == 1
    assert not ctx.file_svc._store.exists(ref.sha256)


def test_unreferenced_object_within_grace_period_is_protected(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("doc")
    make_collection("study")
    ref = _store(ctx, b"fresh", "fresh.txt")

    report = ctx.gc_svc.run(dry_run=False, grace_days=14)
    assert report.deleted_count == 0
    assert report.protected_by_grace == 1
    assert ctx.file_svc._store.exists(ref.sha256)


def test_soft_deleted_but_not_purged_record_still_protects_its_file(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    """A record in Recently Deleted is still restorable, so its files must
    survive GC until it's actually purged."""
    make_schema("doc", fields=[("attachments", "file_list")])
    make_collection("study")
    ref = _store(ctx, b"trashed", "trashed.txt")
    record = make_record("study", "doc", {"attachments": [ref.to_dict()]})
    ctx.record_svc.delete(str(record.id))
    ctx.commit()

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert report.deleted_count == 0
    assert ctx.file_svc._store.exists(ref.sha256)


def test_purged_record_no_longer_protects_its_file(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("doc", fields=[("attachments", "file_list")])
    make_collection("study")
    ref = _store(ctx, b"gone", "gone.txt")
    record = make_record("study", "doc", {"attachments": [ref.to_dict()]})
    ctx.record_svc.delete(str(record.id))
    ctx.record_svc.purge(str(record.id))
    ctx.commit()

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert report.deleted_count == 1
    assert not ctx.file_svc._store.exists(ref.sha256)


def test_workflow_job_input_data_protects_its_file(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    """A completed/failed job can be rerun at any time, replaying its
    __input__ file references -- so those files must survive GC regardless
    of job status or whether any record references them."""
    make_schema("doc")
    make_collection("study")
    record = make_record("study", "doc")
    ref = _store(ctx, b"job-input", "job-input.csv")

    ctx.job_svc.enqueue_manual(
        "some-workflow",
        record,
        input_data={"files": [ref.to_dict()]},
    )
    ctx.commit()

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert report.deleted_count == 0
    assert ctx.file_svc._store.exists(ref.sha256)


def test_gc_on_an_empty_store_reports_cleanly(ctx: AppContext) -> None:
    report = ctx.gc_svc.run(dry_run=True, grace_days=0)
    assert report.scanned == 0
    assert report.deleted_count == 0
    assert report.stale_scratch_removed == 0


def test_stale_upload_scratch_file_is_swept_but_fresh_one_is_not(
    ctx: AppContext,
) -> None:
    """A .part file is what put_stream() leaves mid-upload; one abandoned by
    an interrupted upload should eventually be reclaimed, but a scratch file
    still being actively written (recent mtime) must survive."""
    store = ctx.file_svc._store
    vc = store._cfg.volumes["default"]
    scratch_dir = store._resolve_path(vc) / ".tmp"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    stale = scratch_dir / "abandoned.part"
    stale.write_bytes(b"partial")
    old = time.time() - 2 * 86400
    os.utime(stale, (old, old))

    fresh = scratch_dir / "in-progress.part"
    fresh.write_bytes(b"partial")

    dry = ctx.gc_svc.run(dry_run=True, grace_days=0)
    assert dry.stale_scratch_removed == 1
    assert stale.exists(), "dry run must not delete"

    applied = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert applied.stale_scratch_removed == 1
    assert not stale.exists()
    assert fresh.exists()

    # never surfaced as a real object either
    assert ctx.file_svc._store.list_objects() == []
