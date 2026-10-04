"""Transfers on background threads, as the server runs them: start, watch,
pause, resume, cancel, and carry on by themselves when a drive comes back."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import pytest

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.exceptions import ValidationError
from civex.domain.transfers import (
    KIND_DRAIN,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    TransferRecord,
    TransferSpec,
)
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex.services import transfer_engine, transfer_jobs
from civex.services.transfer_jobs import TransferJobs


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer_engine, "RETRY_DELAY", 0)
    monkeypatch.setattr(transfer_jobs, "AUTO_RESUME_POLL", 0.3)
    # Save progress after every file, so what a test reads at a stop is exact
    # and does not depend on how fast the machine is.
    monkeypatch.setattr(transfer_engine, "FLUSH_FILES", 1)
    monkeypatch.setattr(transfer_engine, "FLUSH_SECONDS", 0)


@pytest.fixture()
def jobs() -> TransferJobs:
    return TransferJobs()


def _volumes(ctx: AppContext, tmp_path: Path, *names: str) -> dict[str, Path]:
    out = {}
    for name in names:
        out[name] = tmp_path / "mnt" / name
        out[name].mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(out[name]))
    return out


def _put_on(ctx: AppContext, volume: str, count: int) -> dict[str, bytes]:
    store = ctx.file_svc._store
    ctx.store_svc.set_queue([volume])
    files = {}
    for i in range(count):
        data = f"{volume} file {i} ".encode() * 60
        files[store.put(data, f"f{i}.txt").sha256] = data
    ctx.commit()
    return files


def _drain(sources, targets, **kw) -> TransferSpec:
    return TransferSpec(kind=KIND_DRAIN, sources=sources, targets=targets, **kw)


def _record(transfer_id: str) -> TransferRecord:
    """The saved record, read the way a web request would: on a fresh, short
    session (a long-lived one would hold the database and block the worker)."""
    ctx = build_local_context(load_config())
    try:
        return ctx.transfer_svc.get(transfer_id)
    finally:
        ctx.close()


# Waiting for an event that must happen: generous, since the bound only matters
# when something is stuck (pytest-timeout also ends a hung test).
SAFETY = 60.0


def _wait(check: Callable[[], bool], what: str, timeout: float = SAFETY) -> None:
    """For things that become true on another thread with nothing to wait on
    (a drive coming back). Everything else uses `Gate` or `jobs.wait`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting for {what}")


def _wait_for_status(
    transfer_id: str, status: str, timeout: float = SAFETY
) -> TransferRecord:
    _wait(lambda: _record(transfer_id).status == status, f"status {status}", timeout)
    return _record(transfer_id)


def _finish(jobs: TransferJobs, transfer_id: str) -> TransferRecord:
    """Let the transfer's thread end, then read what it saved."""
    assert jobs.wait(transfer_id, SAFETY), "the transfer never finished"
    return _record(transfer_id)


class Gate:
    """Hold a transfer in the middle of its n-th copy until the test lets go.

    This replaces "make each copy take a moment and poll until some are done",
    which is a race against the clock. Here the test knows exactly where the
    transfer is: `reached(n)` returns once n copies have run and the next
    thing the transfer does is wait; `release(n)` lets it go on."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, stops: set[int]) -> None:
        self._reached = {n: threading.Event() for n in stops}
        self._go = {n: threading.Event() for n in stops}
        self._count = 0
        real = VolumeAwareFileObjectStore.transfer_object

        def gated(store, *args, **kwargs):
            result = real(store, *args, **kwargs)
            self._count += 1
            if self._count in self._go:
                self._reached[self._count].set()
                assert self._go[self._count].wait(SAFETY), "the gate was never opened"
            return result

        monkeypatch.setattr(VolumeAwareFileObjectStore, "transfer_object", gated)

    def reached(self, n: int) -> None:
        assert self._reached[n].wait(SAFETY), f"never got as far as copy {n}"

    def release(self, n: int) -> None:
        self._go[n].set()

    def release_all(self) -> None:
        for event in self._go.values():
            event.set()


def _store_state(ctx: AppContext, volume: str) -> str:
    return ctx.file_svc._store.volume_status(volume).state


def _contents_intact(files: dict[str, bytes]) -> bool:
    ctx = build_local_context(load_config())
    try:
        return all(ctx.file_svc._store.get(sha) == data for sha, data in files.items())
    finally:
        ctx.close()


# -- the plain case --------------------------------------------------------------


def test_a_transfer_runs_in_the_background_and_completes(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 15)

    started = jobs.start(_drain(["a"], ["b"]))

    assert started.status == STATUS_RUNNING  # returns straight away
    done = _finish(jobs, started.id)
    assert done.status == STATUS_COMPLETED
    assert done.progress.files_done == 15 and done.failures == []
    assert not jobs.is_live(started.id)
    assert _contents_intact(files)


def test_an_impossible_transfer_is_refused_before_anything_starts(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs
) -> None:
    _volumes(ctx, tmp_path, "a")

    with pytest.raises(ValidationError, match="can't be both"):
        jobs.start(_drain(["a"], ["a"]))


def test_progress_can_be_watched_while_it_runs(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 15)
    gate = Gate(monkeypatch, {5, 11})

    started = jobs.start(_drain(["a"], ["b"]))

    gate.reached(5)
    first = _record(started.id)
    assert first.status == STATUS_RUNNING
    assert first.progress.files_done == 4  # the fifth copy is the one in progress
    assert first.progress.current  # and the file being copied is reported
    gate.release(5)

    gate.reached(11)
    second = _record(started.id)
    assert second.progress.files_done == 10  # the count moved between the looks
    gate.release(11)

    done = _finish(jobs, started.id)
    assert done.status == STATUS_COMPLETED and done.progress.files_done == 15
    assert done.progress.current is None  # nothing is "current" at the end


# -- pause, resume, cancel -----------------------------------------------------------


def test_pausing_then_resuming(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 30)
    gate = Gate(monkeypatch, {5})
    started = jobs.start(_drain(["a"], ["b"]))
    gate.reached(5)

    assert jobs.pause(started.id) is True
    gate.release(5)

    paused = _finish(jobs, started.id)
    assert paused.status == STATUS_PAUSED and not paused.auto_resume
    assert 4 <= paused.progress.files_done < 30
    assert _contents_intact(files)  # everything readable, wherever it is
    assert paused.frozen == {"a": "active"}  # the source stays frozen while paused

    jobs.resume(started.id)
    done = _finish(jobs, started.id)

    assert done.status == STATUS_COMPLETED
    assert done.progress.files_done == 30  # each counted once
    assert done.frozen == {}
    assert _contents_intact(files)


def test_cancelling_a_running_transfer_restores_the_source(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 30)
    gate = Gate(monkeypatch, {4})
    started = jobs.start(_drain(["a"], ["b"]))
    gate.reached(4)

    jobs.cancel(started.id)
    gate.release(4)

    done = _finish(jobs, started.id)
    assert done.status == STATUS_CANCELLED
    assert done.progress.files_done < 30 and done.finished_at is not None
    assert load_config().store_config.volumes["a"].state == "active"
    assert _contents_intact(files)


def test_a_paused_transfer_can_be_cancelled_without_running(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 30)
    gate = Gate(monkeypatch, {4})
    started = jobs.start(_drain(["a"], ["b"]))
    gate.reached(4)
    jobs.pause(started.id)
    gate.release(4)
    assert _finish(jobs, started.id).status == STATUS_PAUSED

    closed = jobs.cancel(started.id)

    assert closed is not None and closed.status == STATUS_CANCELLED
    assert load_config().store_config.volumes["a"].state == "active"
    assert _contents_intact(files)


def test_pausing_something_that_is_not_running_says_so(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs
) -> None:
    from civex.domain.exceptions import NotFoundError

    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    started = jobs.start(_drain(["a"], ["b"]))
    assert _finish(jobs, started.id).status == STATUS_COMPLETED

    assert jobs.pause(started.id) is False  # finished: nothing to pause
    with pytest.raises(NotFoundError):
        jobs.pause("00000000-0000-4000-8000-000000000000")


def test_a_running_transfer_cannot_be_started_twice(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b", "c")
    _put_on(ctx, "a", 30)
    gate = Gate(monkeypatch, {2})
    started = jobs.start(_drain(["a"], ["b"]))
    gate.reached(2)  # certainly still running

    with pytest.raises(ValidationError, match="Another transfer is running"):
        jobs.start(_drain(["a"], ["c"]))
    with pytest.raises(ValidationError, match="already running"):
        jobs.resume(started.id)

    jobs.cancel(started.id)
    gate.release(2)
    assert _finish(jobs, started.id).status == STATUS_CANCELLED


# -- a drive that goes away ------------------------------------------------------------


def test_a_transfer_waits_for_a_drive_to_return_and_carries_on_by_itself(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 20)
    unplugged = drives["b"].with_name("b-unplugged")
    real = VolumeAwareFileObjectStore.transfer_object
    count = {"n": 0}

    def unplug_after_five(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        count["n"] += 1
        if count["n"] == 5:
            drives["b"].rename(unplugged)  # the target drive is pulled out
        return result

    monkeypatch.setattr(
        VolumeAwareFileObjectStore, "transfer_object", unplug_after_five
    )
    started = jobs.start(_drain(["a"], ["b"]))

    waiting = _wait_for_status(started.id, STATUS_PAUSED)
    assert waiting.auto_resume and "'b'" in (waiting.pause_reason or "")
    assert jobs.is_live(started.id)  # still there, waiting for it
    # (Files already moved are on the unplugged drive, so they can't be read
    # until it is back; nothing is lost, which is checked at the end.)

    unplugged.rename(drives["b"])  # plugged back in: nobody presses resume

    done = _wait_for_status(started.id, STATUS_COMPLETED)
    assert done.progress.files_done == 20
    assert _contents_intact(files)


def test_pausing_while_waiting_for_a_drive_stops_the_waiting(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 10)
    unplugged = drives["b"].with_name("b-unplugged")
    real = VolumeAwareFileObjectStore.transfer_object
    count = {"n": 0}

    def unplug_after_two(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        count["n"] += 1
        if count["n"] == 2:
            drives["b"].rename(unplugged)
        return result

    monkeypatch.setattr(VolumeAwareFileObjectStore, "transfer_object", unplug_after_two)
    started = jobs.start(_drain(["a"], ["b"]))
    _wait(lambda: _record(started.id).auto_resume, "waiting for the drive")

    jobs.pause(started.id)

    final = _finish(jobs, started.id)  # the waiting thread ends
    assert final.status == STATUS_PAUSED and not final.auto_resume
    unplugged.rename(drives["b"])
    # With no thread left running it, nothing can carry on by itself.
    assert not jobs.is_live(started.id)
    assert _record(started.id).status == STATUS_PAUSED


# -- things that stop it starting ---------------------------------------------------------


def test_a_transfer_that_cannot_start_is_parked_with_the_reason(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)

    with ctx.file_svc._store.gc_lock():  # a garbage-collection pass is running
        started = jobs.start(_drain(["a"], ["b"]))
        parked = _wait_for_status(started.id, STATUS_PAUSED)

    assert "garbage-collection pass is running" in (parked.pause_reason or "")
    assert not parked.auto_resume
    jobs.resume(started.id)  # fine once it has finished
    done = _finish(jobs, started.id)
    assert done.status == STATUS_COMPLETED and done.progress.files_done == 3


def test_resuming_an_unknown_transfer_is_an_error(
    ctx: AppContext, jobs: TransferJobs
) -> None:
    from civex.domain.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        jobs.resume("00000000-0000-4000-8000-000000000000")


def test_threads_are_cleaned_up(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)
    started = jobs.start(_drain(["a"], ["b"]))
    assert _finish(jobs, started.id).status == STATUS_COMPLETED

    assert not jobs._live
    assert not any(t.name.startswith("transfer-") for t in threading.enumerate())


# -- stopping from another process, and cancelling while waiting -----------------------------


def test_a_transfer_running_in_another_process_can_be_paused_from_here(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a terminal-started transfer looks like to the server: it isn't one of
    this process's threads, but the web UI can still pause it."""
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 30)
    gate = Gate(monkeypatch, {4})
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))

    def run_like_the_cli() -> None:
        runner = build_local_context(load_config())
        try:
            runner.transfer_svc.execute(record.id)
        finally:
            runner.close()

    thread = threading.Thread(target=run_like_the_cli)
    thread.start()
    try:
        gate.reached(4)
        assert not jobs.is_live(record.id)  # not one of ours

        assert jobs.pause(record.id) is True
    finally:
        gate.release_all()
        thread.join(timeout=SAFETY)
    assert not thread.is_alive()

    paused = _record(record.id)
    assert paused.status == STATUS_PAUSED
    assert 3 <= paused.progress.files_done < 30
    assert _contents_intact(files)


def test_cancelling_while_waiting_for_a_drive_closes_the_transfer(
    ctx: AppContext, tmp_path: Path, jobs: TransferJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 10)
    unplugged = drives["b"].with_name("b-unplugged")
    real = VolumeAwareFileObjectStore.transfer_object
    count = {"n": 0}

    def unplug_after_two(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        count["n"] += 1
        if count["n"] == 2:
            drives["b"].rename(unplugged)
        return result

    monkeypatch.setattr(VolumeAwareFileObjectStore, "transfer_object", unplug_after_two)
    started = jobs.start(_drain(["a"], ["b"]))
    _wait(lambda: _record(started.id).auto_resume, "waiting for the drive")

    jobs.cancel(started.id)

    closed = _finish(jobs, started.id)
    assert closed.status == STATUS_CANCELLED and closed.finished_at is not None
    assert load_config().store_config.volumes["a"].state == "active"  # unfrozen
    assert not jobs.is_live(started.id)
