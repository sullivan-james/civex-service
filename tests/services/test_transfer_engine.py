"""The transfer engine: moving files between volumes without losing any.

Most of these tests are about what happens when something goes wrong, because
that is the whole point of the engine: it must be safe to stop it, crash it,
corrupt a file under it or pull a drive out from under it at any moment.
"""

from __future__ import annotations

import hashlib
import os
import sys
import shutil
from pathlib import Path

import pytest

from civex.context import AppContext
from civex.domain.transfers import (
    KIND_CONSOLIDATE,
    KIND_FILES,
    KIND_DRAIN,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    TransferSpec,
    TransferStopped,
    VolumeNotResponding,
)
from civex.repositories.local import file_store as file_store_module
from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
from civex.services import transfer_engine
from civex.services.transfer_engine import Outcome, Seed, TransferControl, run_transfer


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer_engine, "RETRY_DELAY", 0)


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


def _volumes(ctx: AppContext, tmp_path: Path, *names: str) -> dict[str, Path]:
    drives = {}
    for name in names:
        drives[name] = _drive(tmp_path, name)
        ctx.store_svc.add_volume(name, str(drives[name]))
    return drives


def _put_on(
    ctx: AppContext, volume: str, count: int, *, size: int = 400
) -> dict[str, bytes]:
    """`count` distinct files stored on `volume`; sha256 -> content."""
    store = ctx.file_svc._store
    ctx.store_svc.set_queue([volume])
    out = {}
    for i in range(count):
        data = f"{volume} file {i} ".encode() * (size // 8)
        ref = store.put(data, f"f{i}.txt")
        assert ref.volume == volume
        out[ref.sha256] = data
    ctx.commit()
    return out


def _on_disk(ctx: AppContext, volume: str) -> set[str]:
    return {o.sha256 for o in ctx.file_svc._store.iter_volume_objects(volume)}


def _catalog(ctx: AppContext, shas) -> dict[str, str]:
    """Where the inventory records each file, its drives joined by "+"."""
    return {
        sha: "+".join(sorted(v for v, _ in rows))
        for sha, rows in ctx.file_svc._store.copies(shas).items()
    }


def _run(
    ctx: AppContext,
    spec: TransferSpec,
    *,
    control: TransferControl | None = None,
    seed: Seed | None = None,
    progress=None,
    placements: dict[str, str] | None = None,
) -> Outcome:
    events: list = []
    return run_transfer(
        ctx.file_svc._store,
        LocalFileReferenceRepository(ctx._session),
        spec,
        placements=placements,
        progress=progress or events.append,
        commit=ctx.commit,
        control=control,
        seed=seed,
    )


def _after_copies(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, n: int, action
) -> None:
    """Run `action` right after the n-th file has been copied: a precise moment
    to pause, cancel or pull a drive, unlike the progress callback, which only
    fires about twice a second."""
    store = ctx.file_svc._store
    real = store.transfer_object
    count = {"n": 0}

    def counted(*args, **kwargs):
        result = real(*args, **kwargs)
        count["n"] += 1
        if count["n"] == n:
            action()
        return result

    monkeypatch.setattr(store, "transfer_object", counted)

    def undo() -> None:
        monkeypatch.setattr(store, "transfer_object", real)

    return undo


def _drain(sources: list[str], targets: list[str], **kw) -> TransferSpec:
    return TransferSpec(kind=KIND_DRAIN, sources=sources, targets=targets, **kw)


def _resume_from(outcome: Outcome) -> Seed:
    return Seed(outcome.progress, outcome.failures, outcome.failures_total)


def _assert_intact(ctx: AppContext, files: dict[str, bytes]) -> None:
    """Every file is still readable, byte for byte, from wherever it is."""
    store = ctx.file_svc._store
    for sha, data in files.items():
        assert store.get(sha) == data


# -- the plain case ---------------------------------------------------------------


def test_a_drain_moves_every_file_and_loses_none(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 20)

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_COMPLETED and outcome.failures == []
    assert outcome.progress.files_done == 20
    assert outcome.progress.bytes_done == sum(len(d) for d in files.values())
    assert _on_disk(ctx, "a") == set() and _on_disk(ctx, "b") == set(files)
    assert set(_catalog(ctx, files).values()) == {"b"}
    _assert_intact(ctx, files)


def test_the_moved_files_keep_their_names_in_the_new_manifest(
    ctx: AppContext, tmp_path: Path
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)

    _run(ctx, _drain(["a"], ["b"]))

    names = ctx.file_svc._store.read_manifest_names("b")
    assert sorted(names.values()) == ["f0.txt", "f1.txt", "f2.txt"]
    assert (drives["b"] / "manifest.jsonl").exists()


def test_drains_work_between_every_kind_of_volume(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Inside-the-project and outside-it volumes take different code paths (the
    second copies on a watched helper thread); both must move everything."""
    _volumes(ctx, tmp_path, "ext")
    files = _put_on(ctx, "default", 5)

    first = _run(ctx, _drain(["default"], ["ext"]))
    back = _run(ctx, _drain(["ext"], ["default"]))

    assert first.status == back.status == STATUS_COMPLETED
    assert _on_disk(ctx, "default") == set(files) and _on_disk(ctx, "ext") == set()
    _assert_intact(ctx, files)


def test_other_volumes_are_left_alone(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b", "c")
    on_a = _put_on(ctx, "a", 4)
    on_c = _put_on(ctx, "c", 4)

    _run(ctx, _drain(["a"], ["b"]))

    assert _on_disk(ctx, "c") == set(on_c)
    assert _on_disk(ctx, "b") == set(on_a)


def test_a_file_that_is_on_both_drives_is_finished_not_copied_again(
    ctx: AppContext, tmp_path: Path
) -> None:
    """What an earlier, interrupted run leaves: the copy is complete on the
    target but the original is still on the source."""
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 3)
    sha = next(iter(files))
    (drives["b"] / sha[:2]).mkdir()
    shutil.copy(drives["a"] / sha[:2] / sha[2:], drives["b"] / sha[:2] / sha[2:])

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_done == 3
    assert _on_disk(ctx, "a") == set()
    _assert_intact(ctx, files)


# -- stopping --------------------------------------------------------------------


def test_pausing_then_resuming_finishes_the_job_exactly_once(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 30)
    control = TransferControl()
    undo = _after_copies(ctx, monkeypatch, 12, control.pause)

    paused = _run(ctx, _drain(["a"], ["b"]), control=control)
    undo()

    assert paused.status == STATUS_PAUSED
    assert paused.progress.files_done == 12
    _assert_intact(ctx, files)  # everything readable mid-way, from either drive
    assert _on_disk(ctx, "a") | _on_disk(ctx, "b") == set(files)
    assert len(_on_disk(ctx, "b")) == 12

    finished = _run(ctx, _drain(["a"], ["b"]), seed=_resume_from(paused))

    assert finished.status == STATUS_COMPLETED
    assert finished.progress.files_done == 30  # counted once each, not twice
    assert _on_disk(ctx, "a") == set() and _on_disk(ctx, "b") == set(files)
    _assert_intact(ctx, files)


def test_cancelling_stops_for_good_and_loses_nothing(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 20)
    control = TransferControl()
    _after_copies(ctx, monkeypatch, 5, control.cancel)

    outcome = _run(ctx, _drain(["a"], ["b"]), control=control)

    assert outcome.status == STATUS_CANCELLED
    assert outcome.progress.files_done == 5
    _assert_intact(ctx, files)
    assert _on_disk(ctx, "a") | _on_disk(ctx, "b") == set(files)


def _scratch_files(drive: Path) -> list[Path]:
    return list((drive / ".tmp").glob("*.part")) if (drive / ".tmp").exists() else []


def test_stopping_in_the_middle_of_a_file_leaves_no_trace_of_it(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Between two volumes inside the project the copy runs inline, and the
    stop is noticed at the very next chunk."""
    from civex.config import VolumeConfig

    store = ctx.file_svc._store
    for name in ("l1", "l2"):
        store._cfg.volumes[name] = VolumeConfig(name=name, path=f"vol-{name}")
        (store._root / f"vol-{name}").mkdir()
    big = os.urandom(3 * 1024 * 1024)  # several chunks
    store._cfg.volume_queue = ["l1"]
    ref = store.put(big, "big.bin")
    ctx.commit()
    seen: list[int] = []

    def stop_after_first_chunk(n: int) -> None:
        seen.append(n)
        raise TransferStopped()

    with pytest.raises(TransferStopped):
        store.transfer_object(ref.sha256, "l1", "l2", on_chunk=stop_after_first_chunk)

    root = ctx.file_svc._store._root
    assert len(seen) == 1, "stopped at the first chunk, not after the copy"
    assert not _scratch_files(root / "vol-l2")
    assert not (root / "vol-l2" / ref.sha256[:2] / ref.sha256[2:]).exists()
    assert store.get(ref.sha256) == big  # the original is untouched


def test_stopping_a_copy_on_the_helper_thread_leaves_no_trace_either(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volume outside the project is copied on a watched helper thread; a stop
    must reach it mid-file and have it clean up after itself."""
    import time

    drives = _volumes(ctx, tmp_path, "a", "b")
    big = os.urandom(3 * 1024 * 1024)
    ctx.store_svc.set_queue(["a"])
    ref = ctx.file_svc._store.put(big, "big.bin")
    ctx.commit()
    # Slow the copy right down so there is a "middle" to stop in.
    monkeypatch.setattr(file_store_module, "_COPY_CHUNK", 64 * 1024)
    real_touch = file_store_module._CopyJob.touch

    def slow_touch(self) -> None:
        time.sleep(0.01)
        real_touch(self)

    monkeypatch.setattr(file_store_module._CopyJob, "touch", slow_touch)

    def stop(n: int) -> None:
        raise TransferStopped()

    with pytest.raises(TransferStopped):
        ctx.file_svc._store.transfer_object(ref.sha256, "a", "b", on_chunk=stop)

    time.sleep(0.2)  # the helper thread notices and tidies up
    assert not _scratch_files(drives["b"])
    assert not (drives["b"] / ref.sha256[:2] / ref.sha256[2:]).exists()
    assert ctx.file_svc._store.get(ref.sha256) == big


# -- crashes ---------------------------------------------------------------------


def test_a_crash_after_copying_but_before_committing_loses_nothing(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog write fails, as if the process died after the copies were
    made: the files are on both drives, the catalog still says the source."""
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 8)
    store = ctx.file_svc._store
    real = store.record_moves

    def crash(moves):
        raise RuntimeError("power cut")

    monkeypatch.setattr(store, "record_moves", crash)
    crashed = _run(ctx, _drain(["a"], ["b"]))
    monkeypatch.setattr(store, "record_moves", real)

    assert crashed.status == STATUS_FAILED
    assert set(_catalog(ctx, files).values()) == {"a"}  # nothing half-recorded
    _assert_intact(ctx, files)

    recovered = _run(ctx, _drain(["a"], ["b"]))

    assert recovered.status == STATUS_COMPLETED and recovered.progress.files_done == 8
    assert _on_disk(ctx, "a") == set()
    assert set(_catalog(ctx, files).values()) == {"b"}
    _assert_intact(ctx, files)


def test_a_crash_after_committing_but_before_removing_leaves_only_a_stray_copy(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 8)
    store = ctx.file_svc._store
    real = store.remove_from_volume

    def cannot_remove(sha256, volume):
        raise OSError("disk went away")

    monkeypatch.setattr(store, "remove_from_volume", cannot_remove)
    first = _run(ctx, _drain(["a"], ["b"]))
    monkeypatch.setattr(store, "remove_from_volume", real)

    assert first.status == STATUS_COMPLETED  # everything is safely on b
    assert set(_catalog(ctx, files).values()) == {"b"}
    assert _on_disk(ctx, "a") == set(files)  # ...with originals left behind
    _assert_intact(ctx, files)

    second = _run(ctx, _drain(["a"], ["b"]))  # finds the strays on the source

    assert second.status == STATUS_COMPLETED
    assert _on_disk(ctx, "a") == set() and _on_disk(ctx, "b") == set(files)
    _assert_intact(ctx, files)


def test_an_unexpected_error_ends_as_failed_and_can_be_resumed(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 10)
    store = ctx.file_svc._store
    real = store.transfer_object
    calls = {"n": 0}

    def explode_on_fifth(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("something nobody planned for")
        return real(*a, **kw)

    monkeypatch.setattr(store, "transfer_object", explode_on_fifth)
    failed = _run(ctx, _drain(["a"], ["b"]))
    monkeypatch.setattr(store, "transfer_object", real)

    assert failed.status == STATUS_FAILED and "nobody planned for" in (
        failed.error or ""
    )
    assert failed.progress.files_done == 4  # what was safely finished is counted
    _assert_intact(ctx, files)

    finished = _run(ctx, _drain(["a"], ["b"]), seed=_resume_from(failed))
    assert finished.status == STATUS_COMPLETED and finished.progress.files_done == 10


# -- a file that can't be moved ---------------------------------------------------


def test_a_corrupt_source_file_is_reported_and_stays_put(
    ctx: AppContext, tmp_path: Path
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 6)
    bad = sorted(files)[2]
    path = drives["a"] / bad[:2] / bad[2:]
    path.write_bytes(b"x" * len(files[bad]))  # same size, wrong content

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_COMPLETED
    assert outcome.progress.files_done == 5 and outcome.progress.files_failed == 1
    [failure] = outcome.failures
    assert failure.sha256 == bad and failure.volume == "a"
    assert "doesn't match its hash" in failure.reason
    assert _on_disk(ctx, "a") == {bad}  # the odd one out is still where it was
    assert _on_disk(ctx, "b") == set(files) - {bad}
    assert not (drives["b"] / bad[:2] / bad[2:]).exists()


def test_a_file_that_vanished_from_the_source_is_reported_not_fatal(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 5)
    gone = sorted(files)[0]
    store = ctx.file_svc._store
    real = store.transfer_object

    def vanish(sha256, source, target, **kw):
        if sha256 == gone:
            (
                store._resolve_path(store._cfg.volumes[source])
                / sha256[:2]
                / sha256[2:]
            ).unlink()
        return real(sha256, source, target, **kw)

    monkeypatch.setattr(store, "transfer_object", vanish)
    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_failed == 1
    assert "no longer on 'a'" in outcome.failures[0].reason
    assert outcome.progress.files_done == 4


def test_full_verification_catches_a_copy_that_does_not_read_back(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 3)
    real = file_store_module._hash_file

    def reads_back_wrong(path, job=None):
        return "0" * 64 if ".part" in path.name else real(path, job)

    monkeypatch.setattr(file_store_module, "_hash_file", reads_back_wrong)
    outcome = _run(ctx, _drain(["a"], ["b"], verify="full"))

    assert outcome.progress.files_failed == 3 and outcome.progress.files_done == 0
    assert "didn't read back correctly" in outcome.failures[0].reason
    assert _on_disk(ctx, "a") == set(files) and _on_disk(ctx, "b") == set()
    _assert_intact(ctx, files)


def test_many_failures_are_all_counted_but_only_some_kept(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civex.domain import transfers

    monkeypatch.setattr(transfer_engine, "MAX_RECORDED_FAILURES", 3)
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 6)
    for sha, data in files.items():
        (drives["a"] / sha[:2] / sha[2:]).write_bytes(b"?" * len(data))

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.failures_total == 6 and len(outcome.failures) == 3
    assert transfers.MAX_RECORDED_FAILURES == 200  # the real limit is untouched


# -- room ------------------------------------------------------------------------


def test_files_fill_the_targets_in_order(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b", "c")
    files = _put_on(ctx, "a", 10, size=4096)
    # b has room for roughly four of the 4 KiB files.
    ctx.file_svc._store._cfg.volumes["b"].allocated_gb = 17_000 / 1024**3

    outcome = _run(ctx, _drain(["a"], ["b", "c"]))

    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_done == 10
    on_b, on_c = _on_disk(ctx, "b"), _on_disk(ctx, "c")
    assert 3 <= len(on_b) <= 5 and len(on_b) + len(on_c) == 10
    _assert_intact(ctx, files)


def test_with_no_room_anywhere_it_pauses_and_says_why(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 5)
    ctx.file_svc._store._cfg.volumes["b"].allocated_gb = 0

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_PAUSED and not outcome.auto_resume
    assert "No target has room" in (outcome.pause_reason or "")
    assert _on_disk(ctx, "a") == set(files) and _on_disk(ctx, "b") == set()


def test_a_read_only_target_is_not_written_to(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)
    ctx.file_svc._store._cfg.volumes["b"].state = "readonly"

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_PAUSED
    assert _on_disk(ctx, "b") == set()


# -- volumes that go quiet --------------------------------------------------------


def test_an_unplugged_target_pauses_to_resume_by_itself(
    ctx: AppContext, tmp_path: Path
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 6)
    drives["b"].rename(drives["b"].with_name("b-unplugged"))

    outcome = _run(ctx, _drain(["a"], ["b"]))

    assert outcome.status == STATUS_PAUSED and outcome.auto_resume
    assert "'b'" in (outcome.pause_reason or "")
    _assert_intact(ctx, files)

    drives["b"].with_name("b-unplugged").rename(drives["b"])
    resumed = _run(ctx, _drain(["a"], ["b"]), seed=_resume_from(outcome))

    assert resumed.status == STATUS_COMPLETED and _on_disk(ctx, "b") == set(files)


@pytest.mark.posix_only
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows will not rename a folder holding open files",
)
def test_a_source_that_vanishes_part_way_is_not_mistaken_for_an_empty_one(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 12)
    unplugged = drives["a"].with_name("a-unplugged")
    undo = _after_copies(ctx, monkeypatch, 4, lambda: drives["a"].rename(unplugged))

    outcome = _run(ctx, _drain(["a"], ["b"]))
    undo()

    assert outcome.status == STATUS_PAUSED and outcome.auto_resume
    assert "'a'" in (outcome.pause_reason or "")
    assert outcome.progress.files_done < 12

    unplugged.rename(drives["a"])
    finished = _run(ctx, _drain(["a"], ["b"]), seed=_resume_from(outcome))
    assert finished.status == STATUS_COMPLETED and finished.progress.files_done == 12
    _assert_intact(ctx, files)


def test_a_copy_that_moves_no_bytes_is_treated_as_a_quiet_volume(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write to a dead network share can block forever and can't be
    interrupted from outside, so a copy that stalls is abandoned."""
    import time

    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 1)
    sha = next(iter(files))
    store = ctx.file_svc._store
    monkeypatch.setattr(file_store_module, "STALL_SECONDS", 0.3)
    monkeypatch.setattr(store, "_copy_blocking", lambda *a, **k: time.sleep(3))

    started = time.monotonic()
    with pytest.raises(VolumeNotResponding):
        store.transfer_object(sha, "a", "b")

    assert time.monotonic() - started < 2
    assert store.get(sha) == files[sha]


# -- consolidating a collection ---------------------------------------------------


def _collection_with_files(
    ctx, make_schema, make_collection, make_record, name, contents
):
    make_collection(name)
    refs = []
    for i, data in enumerate(contents):
        ref = ctx.file_svc.store_bytes(data, f"{name}{i}.txt")
        make_record(name, "doc", {"scan": ref.to_dict()})
        refs.append(ref)
    ctx.commit()
    return refs


def test_consolidating_moves_a_collections_files_and_only_those(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    _volumes(ctx, tmp_path, "a", "b", "home")
    make_schema("doc", fields=[("scan", "file")])
    ctx.store_svc.set_queue(["a"])
    mine = _collection_with_files(
        ctx, make_schema, make_collection, make_record, "mine", [b"m1" * 99, b"m2" * 99]
    )
    ctx.store_svc.set_queue(["b"])
    other = _collection_with_files(
        ctx, make_schema, make_collection, make_record, "other", [b"o1" * 99]
    )
    cid = str(ctx.dataset_svc.get("mine").id)

    outcome = _run(
        ctx, TransferSpec(kind=KIND_CONSOLIDATE, targets=["home"], collection_ids=[cid])
    )

    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_done == 2
    assert _catalog(ctx, [r.sha256 for r in mine]) == {r.sha256: "home" for r in mine}
    assert _catalog(ctx, [r.sha256 for r in other]) == {other[0].sha256: "b"}
    for ref, data in zip(mine, [b"m1" * 99, b"m2" * 99]):
        assert ctx.file_svc._store.get(ref.sha256) == data


def test_files_already_home_are_skipped(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    _volumes(ctx, tmp_path, "a", "home")
    make_schema("doc", fields=[("scan", "file")])
    ctx.store_svc.set_queue(["home"])
    refs = _collection_with_files(
        ctx, make_schema, make_collection, make_record, "mine", [b"x" * 90, b"y" * 90]
    )
    cid = str(ctx.dataset_svc.get("mine").id)

    outcome = _run(
        ctx, TransferSpec(kind=KIND_CONSOLIDATE, targets=["home"], collection_ids=[cid])
    )

    assert outcome.progress.files_done == 0 and outcome.progress.files_skipped == 2
    assert set(_catalog(ctx, [r.sha256 for r in refs]).values()) == {"home"}


def test_a_file_on_another_collections_home_is_copied_not_moved(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    """A home keeps a copy of every file its collection uses: gathering `mine`
    onto its home copies a file `theirs` keeps on its own home (both homes
    then hold it) and moves the rest."""
    _volumes(ctx, tmp_path, "a", "home", "elsewhere")
    make_schema("doc", fields=[("scan", "file")])
    make_collection("mine")
    make_collection("theirs")
    ctx.store_svc.set_queue(["elsewhere"])
    shared = ctx.file_svc.store_bytes(b"shared " * 40, "shared.txt")
    ctx.store_svc.set_queue(["a"])
    private = ctx.file_svc.store_bytes(b"private " * 40, "private.txt")
    make_record("mine", "doc", {"scan": shared.to_dict()})
    make_record("mine", "doc", {"scan": private.to_dict()})
    make_record("theirs", "doc", {"scan": shared.to_dict()})
    ctx.commit()
    mine_id = str(ctx.dataset_svc.get("mine").id)
    theirs_id = str(ctx.dataset_svc.get("theirs").id)
    homes = {theirs_id: "elsewhere", mine_id: "home"}

    spec = TransferSpec(
        kind=KIND_CONSOLIDATE, targets=["home"], collection_ids=[mine_id]
    )
    done = _run(ctx, spec, placements=homes)

    assert done.progress.files_done == 2
    assert _catalog(ctx, [shared.sha256, private.sha256]) == {
        shared.sha256: "elsewhere+home",  # copied: `theirs` keeps its copy
        private.sha256: "home",  # moved
    }
    assert shared.sha256 in _on_disk(ctx, "elsewhere")
    assert private.sha256 not in _on_disk(ctx, "a")

    again = _run(ctx, spec, placements=homes)  # nothing left to do
    assert again.progress.files_done == 0 and again.progress.files_skipped == 2


def test_emptying_a_drive_whose_files_the_target_has_says_they_were_there(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    """Draining a drive whose files the target already holds only removes the
    originals: each counts as already there, so the move doesn't finish at
    "0 of N files" after emptying the drive."""
    _volumes(ctx, tmp_path, "a", "b")
    make_schema("doc", fields=[("scan", "file")])
    make_collection("mine")
    ctx.store_svc.set_queue(["a"])
    refs = [ctx.file_svc.store_bytes(d, "f.txt") for d in (b"x" * 90, b"y" * 70)]
    for ref in refs:
        make_record("mine", "doc", {"scan": ref.to_dict()})
    ctx.commit()
    home = {str(ctx.dataset_svc.get("mine").id): "a"}
    shas = [r.sha256 for r in refs]
    _run(ctx, TransferSpec(kind=KIND_FILES, targets=["b"], shas=shas), placements=home)
    assert set(_catalog(ctx, shas).values()) == {"a+b"}  # copied: a is the home

    emptied = _run(ctx, _drain(["b"], ["a"]), placements=home)

    p = emptied.progress
    assert (p.files_done, p.files_skipped, p.files_total) == (0, 2, 2)
    assert p.bytes_total == 0  # nothing had to be carried
    assert _on_disk(ctx, "b") == set()
    assert set(_catalog(ctx, shas).values()) == {"a"}


# -- progress --------------------------------------------------------------------


def test_progress_is_reported_as_it_goes(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 25, size=2000)
    seen = []

    outcome = _run(ctx, _drain(["a"], ["b"]), progress=seen.append)

    assert seen and seen[0].files_done == 0
    done = [p.files_done for p in seen]
    assert done == sorted(done), "progress never goes backwards"
    assert outcome.progress.files_done == outcome.progress.files_total == 25
    assert (
        outcome.progress.bytes_done
        == outcome.progress.bytes_total
        == sum(len(d) for d in files.values())
    )
    assert outcome.progress.current is None and outcome.progress.message == "Finished"


def test_the_total_grows_to_match_what_is_found(
    ctx: AppContext, tmp_path: Path
) -> None:
    """The plan's numbers come from the catalog; the run counts the disk."""
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 8)

    outcome = _run(
        ctx, _drain(["a"], ["b"]), seed=Seed(progress=_progress(files_total=3))
    )

    assert outcome.progress.files_total == 8 == outcome.progress.files_done
    assert outcome.progress.bytes_total == sum(len(d) for d in files.values())


def _progress(**kw):
    from civex.domain.transfers import TransferProgress

    return TransferProgress(**kw)


def test_a_resumed_run_carries_on_from_the_earlier_totals(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 4)
    seed = Seed(
        progress=_progress(
            files_total=10, files_done=6, bytes_total=9999, bytes_done=5000
        )
    )

    outcome = _run(ctx, _drain(["a"], ["b"]), seed=seed)

    assert outcome.progress.files_done == 10  # 6 from before + 4 now
    assert outcome.progress.files_total == 10


def test_a_transfer_is_never_confused_by_the_hash_of_what_it_moves(
    ctx: AppContext, tmp_path: Path
) -> None:
    """The moved bytes really are the original bytes (the hash is the proof)."""
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 5)

    _run(ctx, _drain(["a"], ["b"], verify="full"))

    store = ctx.file_svc._store
    for sha in files:
        assert hashlib.sha256(store.get(sha)).hexdigest() == sha


def test_a_copy_flushing_a_large_file_gets_longer_before_it_counts_as_stalled() -> None:
    job = file_store_module._CopyJob()
    job.size = 10 * 1024**3  # 10 GiB
    assert job.stall_limit() == file_store_module.STALL_SECONDS
    job.syncing = True
    assert job.stall_limit() > file_store_module.STALL_SECONDS
    job.size = 1024
    assert job.stall_limit() == file_store_module.STALL_SECONDS


def test_a_files_transfer_moves_exactly_the_named_files(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    _volumes(ctx, tmp_path, "a", "home")
    make_schema("doc", fields=[("scan", "file")])
    ctx.store_svc.set_queue(["a"])
    refs = _collection_with_files(
        ctx,
        make_schema,
        make_collection,
        make_record,
        "mine",
        [b"one" * 99, b"two" * 99, b"three" * 99],
    )
    chosen = [refs[0].sha256, refs[2].sha256]

    outcome = _run(ctx, TransferSpec(kind=KIND_FILES, targets=["home"], shas=chosen))

    # The rest of the collection stays where it was.
    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_done == 2
    assert _catalog(ctx, [r.sha256 for r in refs]) == {
        refs[0].sha256: "home",
        refs[1].sha256: "a",
        refs[2].sha256: "home",
    }
    assert ctx.file_svc._store.get(refs[2].sha256) == b"three" * 99


def test_a_files_transfer_leaves_files_already_on_the_target_alone(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    _volumes(ctx, tmp_path, "a", "home")
    make_schema("doc", fields=[("scan", "file")])
    ctx.store_svc.set_queue(["home"])
    refs = _collection_with_files(
        ctx, make_schema, make_collection, make_record, "mine", [b"x" * 90]
    )

    outcome = _run(
        ctx,
        TransferSpec(kind=KIND_FILES, targets=["home"], shas=[refs[0].sha256]),
    )

    assert outcome.progress.files_done == 0 and outcome.progress.files_skipped == 1


def test_a_files_transfer_ignores_content_that_is_stored_nowhere(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "home")

    outcome = _run(
        ctx, TransferSpec(kind=KIND_FILES, targets=["home"], shas=["ab" * 32])
    )

    assert outcome.status == STATUS_COMPLETED and outcome.progress.files_done == 0
