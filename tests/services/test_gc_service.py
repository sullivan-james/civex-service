"""GCService: mark-and-sweep over the content-addressed object store."""

from __future__ import annotations

import os
import time

import pytest

from civex.context import AppContext
from civex.domain.exceptions import GCAlreadyRunningError, ValidationError


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


def _two_volumes(ctx: AppContext, tmp_path):
    for name in ("a", "b"):
        path = tmp_path / "mnt" / name
        path.mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(path))


def test_clean_up_can_be_limited_to_one_volume(
    ctx: AppContext, tmp_path, make_schema, make_collection
) -> None:
    make_schema("doc")
    make_collection("study")
    _two_volumes(ctx, tmp_path)
    store = ctx.file_svc._store
    ctx.store_svc.set_queue(["a"])
    on_a = _store(ctx, b"orphan on a", "a.txt")
    ctx.store_svc.set_queue(["b"])
    on_b = _store(ctx, b"orphan on b", "b.txt")

    dry = ctx.gc_svc.run(dry_run=True, grace_days=0, volume="a")
    assert [o.sha256 for o in dry.deleted] == [on_a.sha256]
    assert dry.volume == "a" and dry.scanned == 1  # only that volume was looked at

    ctx.gc_svc.run(dry_run=False, grace_days=0, volume="a")
    assert not store.exists(on_a.sha256)
    assert store.exists(on_b.sha256), "the other volume is left alone"

    everything = ctx.gc_svc.run(dry_run=True, grace_days=0)
    assert [o.sha256 for o in everything.deleted] == [on_b.sha256]
    assert everything.volume is None


def test_clean_up_of_an_unknown_volume_is_not_found(ctx: AppContext) -> None:
    from civex.domain.exceptions import NotFoundError

    with pytest.raises(NotFoundError, match="nowhere"):
        ctx.gc_svc.run(dry_run=True, grace_days=0, volume="nowhere")


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


def test_unreadable_reference_source_reports_error_and_deletes_nothing(
    ctx: AppContext, make_schema, make_collection, monkeypatch
) -> None:
    """A reference lookup that fails must not crash the
    whole GC pass, and must not let the run delete anything -- an
    incomplete reference set could otherwise make a still-live object look
    collectible."""
    make_schema("doc")
    make_collection("study")
    ref = _store(ctx, b"orphan", "orphan.txt")

    def _boom():
        raise RuntimeError("corrupt row")

    monkeypatch.setattr(ctx.gc_svc._refs, "copies_in_use", lambda copies: _boom())

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)

    assert report.errors and "file references" in report.errors[0]
    assert ctx.file_svc._store.exists(ref.sha256)  # nothing deleted on error


def test_overlapping_gc_runs_are_rejected(ctx: AppContext) -> None:
    with ctx.file_svc._store.gc_lock():
        with pytest.raises(GCAlreadyRunningError):
            ctx.gc_svc.run(dry_run=True, grace_days=0)

    # Lock released -- a subsequent run works normally.
    ctx.gc_svc.run(dry_run=True, grace_days=0)


def test_stale_gc_lock_is_reclaimed(ctx: AppContext) -> None:
    from civex.repositories.local.file_store import _GC_LOCK_STALE_SECONDS

    store = ctx.file_svc._store
    lock_path = store._root / "_civex" / ".gc.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()
    old = time.time() - _GC_LOCK_STALE_SECONDS - 1
    os.utime(lock_path, (old, old))

    # Doesn't raise -- the stale lock is reclaimed rather than blocking forever.
    ctx.gc_svc.run(dry_run=True, grace_days=0)


def _dead_pid() -> int:
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_gc_lock_of_a_dead_process_is_reclaimed_at_once(ctx: AppContext) -> None:
    lock_path = ctx.file_svc._store._root / "_civex" / ".gc.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(_dead_pid()))  # fresh, so only the dead owner frees it

    ctx.gc_svc.run(dry_run=True, grace_days=0)  # doesn't raise


def test_gc_lock_of_a_live_process_still_blocks(ctx: AppContext) -> None:
    from civex.domain.exceptions import GCAlreadyRunningError

    lock_path = ctx.file_svc._store._root / "_civex" / ".gc.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()))

    with pytest.raises(GCAlreadyRunningError):
        ctx.gc_svc.run(dry_run=True, grace_days=0)


def test_negative_grace_days_is_rejected(ctx: AppContext) -> None:
    with pytest.raises(ValidationError):
        ctx.gc_svc.run(dry_run=True, grace_days=-1)


def test_reference_table_tracks_record_writes_and_purge(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    """file_references is maintained by ORM events on every record write,
    and emptied by ON DELETE CASCADE when the record is purged."""
    from civex.domain.file_refs import collect_sha256_refs  # noqa: F401
    from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository

    refs = LocalFileReferenceRepository(ctx._session)
    make_schema("doc", fields=[("attachments", "file_list")])
    make_collection("study")
    a = _store(ctx, b"a", "a.txt")
    b = _store(ctx, b"b", "b.txt")
    rec = make_record("study", "doc", {"attachments": [a.to_dict()]})
    ctx.commit()
    assert refs.referenced_subset([a.sha256, b.sha256]) == {a.sha256}

    ctx.record_svc.update(str(rec.id), {"attachments": [b.to_dict()]})
    ctx.commit()
    assert refs.referenced_subset([a.sha256, b.sha256]) == {b.sha256}

    ctx.record_svc.delete(str(rec.id))
    ctx.commit()
    # soft-deleted records still protect their files (they're restorable)
    assert refs.referenced_subset([b.sha256]) == {b.sha256}

    ctx.record_svc.purge(str(rec.id))
    ctx.commit()
    assert refs.referenced_subset([a.sha256, b.sha256]) == set()


def test_rebuild_references_recovers_from_a_wiped_table(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    from sqlalchemy import delete

    from civex.db.models import FileReference

    make_schema("doc", fields=[("attachments", "file_list")])
    make_collection("study")
    ref = _store(ctx, b"kept", "kept.txt")
    make_record("study", "doc", {"attachments": [ref.to_dict()]})
    ctx.commit()

    ctx._session.execute(delete(FileReference))
    assert ctx.gc_svc.rebuild_references() == 1
    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert report.deleted_count == 0
    assert ctx.file_svc._store.exists(ref.sha256)


def test_gc_processes_more_objects_than_one_batch(ctx: AppContext, monkeypatch) -> None:
    import civex.services.gc_service as gc

    monkeypatch.setattr(gc, "_BATCH", 3)
    refs = [_store(ctx, f"blob-{i}".encode(), f"{i}.txt") for i in range(10)]
    report = ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert report.scanned == 10
    assert report.deleted_count == 10
    assert not any(ctx.file_svc._store.exists(r.sha256) for r in refs)


def test_volume_usage_comes_from_inventory_and_heals_on_gc(ctx: AppContext) -> None:
    store = ctx.file_svc._store
    a = store.put(b"x" * 100, "a")
    store.put(b"y" * 50, "b")
    assert store._civex_used("default") == 150

    # Drift: a blob vanishes behind the store's back.
    store._object_path(a.sha256, "default").unlink()
    assert store._civex_used("default") == 150  # stale until reconciled
    ctx.gc_svc.run(dry_run=False, grace_days=0)
    assert store._civex_used("default") == 0  # both unreferenced -> deleted


def test_dedupe_hit_refreshes_mtime_so_grace_protects_it(ctx: AppContext) -> None:
    store = ctx.file_svc._store
    ref = store.put(b"again", "a.txt")
    path = store.object_path(ref.sha256)
    old = time.time() - 40 * 86400
    os.utime(path, (old, old))
    store.put(b"again", "a.txt")  # user re-uploads the same bytes
    assert path.stat().st_mtime > old + 86400
    report = ctx.gc_svc.run(dry_run=False, grace_days=14)
    assert report.deleted_count == 0


def test_no_grace_period_spares_nothing_even_a_file_stamped_ahead(
    ctx: AppContext, monkeypatch
) -> None:
    """With grace_days=0 nothing is protected, even a file whose timestamp is a
    little ahead of the clock (Windows file times can be), which compared with
    "now" once made the last file written look too new to collect."""
    import civex.services.gc_service as gc

    ref = _store(ctx, b"written just now", "now.txt")
    path = ctx.file_svc._store.object_path(ref.sha256)
    ahead = gc.time.time() + 5
    os.utime(path, (ahead, ahead))

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)

    assert [o.sha256 for o in report.deleted] == [ref.sha256]
    assert report.protected_by_grace == 0


def test_a_duplicate_nothing_points_at_is_reclaimed_and_the_used_copy_kept(
    ctx: AppContext, make_schema, make_collection, make_record, tmp_path
) -> None:
    """A record uses one copy of a file; an identical copy on another drive that
    nothing points at is a duplicate, reclaimable like any unused file. The
    copy in use stays."""
    other = tmp_path / "other-drive"
    ctx.store_svc.add_volume("other", str(other))
    make_schema("doc", fields=[("scan", "file")])
    make_collection("study")
    ref = _store(ctx, b"the same bytes", "a.txt")  # on default
    record = make_record("study", "doc", {"scan": ref.to_dict()})
    store = ctx.file_svc._store
    store.record_moves([(ref.sha256, "other", ref.size)])  # a second copy...
    path = store.path_on(ref.sha256, "other")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"the same bytes")  # ...really there, that nothing uses
    ctx.commit()
    assert store.copies_used([record.id]) == {(record.id, ref.sha256): "default"}

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)

    assert [(o.sha256, o.volume) for o in report.deleted] == [(ref.sha256, "other")]
    assert not path.exists()
    assert store.path_on(ref.sha256, "default").exists()


def test_every_copy_stays_when_the_one_records_point_at_is_missing(
    ctx: AppContext, make_schema, make_collection, make_record, tmp_path
) -> None:
    """If the copy a record points at isn't recorded, the clean-up can't tell a
    duplicate from the last real copy: it keeps them all."""
    other = tmp_path / "other-drive"
    ctx.store_svc.add_volume("other", str(other))
    make_schema("doc", fields=[("scan", "file")])
    make_collection("study")
    ref = _store(ctx, b"precious", "p.txt")
    make_record("study", "doc", {"scan": ref.to_dict()})
    store = ctx.file_svc._store
    store.record_moves([(ref.sha256, "other", ref.size)])
    path = store.path_on(ref.sha256, "other")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"precious")
    from sqlalchemy import text

    # The record still points at "default", but that copy has gone from the
    # inventory (drift): "other" is the only copy known.
    ctx._session.execute(
        text("DELETE FROM stored_objects WHERE sha256 = :s AND volume = 'default'"),
        {"s": ref.sha256},
    )
    ctx.commit()

    report = ctx.gc_svc.run(dry_run=True, grace_days=0)

    assert all(o.sha256 != ref.sha256 for o in report.deleted)
