"""Planning a transfer, keeping its record, freezing the source, recovering."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import update

from civex import fs_locations
from civex.context import AppContext, build_local_context
from civex.config import load_config
from civex.db.models import StorageTransfer
from civex.domain.exceptions import (
    GCAlreadyRunningError,
    NotFoundError,
    ValidationError,
)
from civex.domain.transfers import (
    KIND_CONSOLIDATE,
    KIND_DRAIN,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_INTERRUPTED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    TransferSpec,
)
from civex.services import transfer_engine
from civex.services.transfer_engine import TransferControl
from civex.services.transfer_service import INTERRUPTED_REASON


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer_engine, "RETRY_DELAY", 0)


def _volumes(ctx: AppContext, tmp_path: Path, *names: str) -> dict[str, Path]:
    out = {}
    for name in names:
        out[name] = tmp_path / "mnt" / name
        out[name].mkdir(parents=True)
        ctx.store_svc.add_volume(name, str(out[name]))
    return out


def _put_on(
    ctx: AppContext, volume: str, count: int, size: int = 400
) -> dict[str, bytes]:
    store = ctx.file_svc._store
    ctx.store_svc.set_queue([volume])
    files = {}
    for i in range(count):
        data = f"{volume} file {i} ".encode() * (size // 8)
        files[store.put(data, f"f{i}.txt").sha256] = data
    ctx.commit()
    return files


def _drain(sources, targets, **kw) -> TransferSpec:
    return TransferSpec(kind=KIND_DRAIN, sources=sources, targets=targets, **kw)


def _state(ctx: AppContext, volume: str) -> str:
    return ctx.file_svc._store.volume_status(volume).state


# -- planning ---------------------------------------------------------------------


def test_a_drain_is_sized_from_the_catalog(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 10)

    plan = ctx.transfer_svc.plan(_drain(["a"], ["b"]))

    assert plan.can_proceed and plan.problems == []
    assert plan.files == 10 and plan.bytes == sum(len(d) for d in files.values())
    [target] = plan.targets
    assert target.volume == "b" and target.bytes == plan.bytes and target.free_bytes


def test_a_drain_that_will_not_fit_says_so(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 10, size=4096)
    ctx.file_svc._store._cfg.volumes["b"].allocated_gb = 10_000 / 1024**3

    plan = ctx.transfer_svc.plan(_drain(["a"], ["b"]))

    assert not plan.can_proceed
    assert any("targets have room for" in p for p in plan.problems)


def test_the_targets_are_shared_out_in_order(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b", "c")
    _put_on(ctx, "a", 10, size=4096)
    ctx.file_svc._store._cfg.volumes["b"].allocated_gb = 17_000 / 1024**3

    plan = ctx.transfer_svc.plan(_drain(["a"], ["b", "c"]))

    assert plan.can_proceed
    b, c = plan.targets
    assert 0 < b.bytes < plan.bytes and b.bytes + c.bytes == plan.bytes


@pytest.mark.parametrize(
    "spec, expect",
    [
        (_drain(["a"], []), "at least one volume"),
        (_drain([], ["b"]), "which volume to move the files off"),
        (_drain(["nope"], ["b"]), "no volume called 'nope'"),
        (_drain(["a"], ["a"]), "can't be both"),
        (_drain(["a"], ["b", "b"]), "listed twice"),
        (
            TransferSpec(kind="shuffle", targets=["b"], sources=["a"]),
            "A transfer is one of",
        ),
        (_drain(["a"], ["b"], verify="trust-me"), "Verification is one of"),
        (TransferSpec(kind=KIND_CONSOLIDATE, targets=["b"]), "which collection"),
        (
            TransferSpec(
                kind=KIND_CONSOLIDATE, targets=["b"], collection_ids=["not-a-uuid"]
            ),
            "not a collection id",
        ),
        (
            TransferSpec(
                kind=KIND_CONSOLIDATE,
                targets=["b"],
                collection_ids=["3f2b8c1e-0000-4000-8000-123456789abc"],
            ),
            "no longer exists",
        ),
    ],
)
def test_a_badly_formed_transfer_is_refused_with_a_reason(
    ctx: AppContext, tmp_path: Path, spec: TransferSpec, expect: str
) -> None:
    _volumes(ctx, tmp_path, "a", "b")

    plan = ctx.transfer_svc.plan(spec)

    assert not plan.can_proceed and any(expect in p for p in plan.problems), (
        plan.problems
    )


def test_an_offline_source_or_read_only_target_is_refused(
    ctx: AppContext, tmp_path: Path
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    ctx.file_svc._store._cfg.volumes["b"].state = "readonly"
    assert any(
        "'b' can't be written to" in p
        for p in ctx.transfer_svc.plan(_drain(["a"], ["b"])).problems
    )

    ctx.file_svc._store._cfg.volumes["b"].state = "active"
    drives["a"].rename(drives["a"].with_name("a-unplugged"))
    assert any(
        "'a' isn't available" in p
        for p in ctx.transfer_svc.plan(_drain(["a"], ["b"])).problems
    )


def test_plans_carry_warnings_that_matter(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    monkeypatch.setattr(fs_locations, "is_network_path", lambda path, mounts=None: True)

    warnings = " ".join(
        ctx.transfer_svc.plan(_drain(["a"], ["b"], verify="full")).warnings
    )

    assert "'a' will be made read-only while this runs" in warnings
    assert "Network drives" in warnings and "carries on by itself" in warnings
    assert "Full verification" in warnings
    quiet = ctx.transfer_svc.plan(_drain(["a"], ["b"], freeze_sources=False))
    assert "read-only" not in " ".join(quiet.warnings)


def test_draining_a_volume_with_nothing_on_it_warns(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")

    plan = ctx.transfer_svc.plan(_drain(["a"], ["b"]))

    assert plan.can_proceed and plan.files == 0
    assert any("nothing to move" in w for w in plan.warnings)


def test_consolidating_is_sized_and_says_what_stays(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
) -> None:
    _volumes(ctx, tmp_path, "a", "home", "elsewhere")
    make_schema("doc", fields=[("scan", "file")])
    ctx.store_svc.set_queue(["a"])
    make_collection("mine")
    make_collection("theirs")
    shared = ctx.file_svc.store_bytes(b"shared " * 40, "s.txt")
    private = ctx.file_svc.store_bytes(b"private " * 40, "p.txt")
    make_record("mine", "doc", {"scan": shared.to_dict()})
    make_record("mine", "doc", {"scan": private.to_dict()})
    make_record("theirs", "doc", {"scan": shared.to_dict()})
    ctx.commit()
    mine, theirs = (
        str(ctx.dataset_svc.get("mine").id),
        str(ctx.dataset_svc.get("theirs").id),
    )
    ctx.store_svc.set_placement(theirs, "elsewhere")

    spec = TransferSpec(kind=KIND_CONSOLIDATE, targets=["home"], collection_ids=[mine])
    plan = ctx.transfer_svc.plan(spec)

    assert plan.files == 1 and plan.shared_left == 1
    assert any("kept elsewhere" in w for w in plan.warnings)
    spec.include_shared = True
    assert ctx.transfer_svc.plan(spec).files == 2


# -- the saved record -------------------------------------------------------------


def test_creating_a_transfer_saves_it_as_running_with_its_plan(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 5)

    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))

    saved = ctx.transfer_svc.get(record.id)
    assert saved.status == STATUS_RUNNING and saved.kind == KIND_DRAIN
    assert saved.spec.sources == ["a"] and saved.spec.targets == ["b"]
    assert saved.progress.files_total == 5
    assert saved.progress.bytes_total == sum(len(d) for d in files.values())
    assert saved.plan is not None and saved.plan.files == 5
    assert saved.started_at is not None and saved.created_at is not None


def test_creating_an_impossible_transfer_raises_with_every_reason(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a")

    with pytest.raises(ValidationError, match="can't be both"):
        ctx.transfer_svc.create(_drain(["a"], ["a"]))
    assert ctx.transfer_svc.recent() == []


def test_unknown_transfers_are_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError):
        ctx.transfer_svc.get("00000000-0000-4000-8000-000000000000")
    with pytest.raises(NotFoundError):
        ctx.transfer_svc.get("not-an-id")


def test_only_one_transfer_runs_at_a_time(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b", "c")
    _put_on(ctx, "a", 2)
    ctx.transfer_svc.create(_drain(["a"], ["b"]))

    with pytest.raises(ValidationError, match="Another transfer is running"):
        ctx.transfer_svc.create(_drain(["a"], ["c"]))


# -- running it ----------------------------------------------------------------------


def test_executing_runs_it_to_the_end_and_saves_how_it_went(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 12)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))

    done = ctx.transfer_svc.execute(record.id)

    assert done.status == STATUS_COMPLETED and done.finished_at is not None
    saved = ctx.transfer_svc.get(record.id)
    assert saved.status == STATUS_COMPLETED
    assert saved.progress.files_done == saved.progress.files_total == 12
    assert saved.progress.message == "Finished" and saved.failures == []
    store = ctx.file_svc._store
    assert all(store.get(sha) == data for sha, data in files.items())


def test_progress_is_saved_while_it_runs(ctx: AppContext, tmp_path: Path) -> None:
    """What a progress bar reads: the saved record changes during the run."""
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 20, size=2000)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    seen: list[int] = []

    ctx.transfer_svc.execute(
        record.id,
        on_progress=lambda p: seen.append(
            ctx.transfer_svc.get(record.id).progress.files_done
        ),
    )

    assert len(seen) >= 2 and seen == sorted(seen) and seen[-1] == 20


def test_the_source_is_read_only_while_it_is_emptied_and_restored_after(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 6)
    ctx.store_svc.set_queue(["a", "b"])
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    during: list[str] = []

    done = ctx.transfer_svc.execute(
        record.id, on_progress=lambda p: during.append(_state(ctx, "a"))
    )

    assert set(during) == {"readonly"}
    assert _state(ctx, "a") == "online" and done.frozen == {}
    assert load_config().store_config.volumes["a"].state == "active"  # and on disk


def test_a_volume_that_was_already_read_only_is_left_as_it_was(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)
    ctx.store_svc.set_volume_state("a", "readonly")
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))

    done = ctx.transfer_svc.execute(record.id)

    assert done.frozen == {} and _state(ctx, "a") == "readonly"


def test_freezing_can_be_turned_off(ctx: AppContext, tmp_path: Path) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"], freeze_sources=False))
    during: list[str] = []

    ctx.transfer_svc.execute(
        record.id, on_progress=lambda p: during.append(_state(ctx, "a"))
    )

    assert set(during) == {"online"}


def test_a_paused_transfer_keeps_its_source_frozen_and_cancelling_restores_it(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 10)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    control = TransferControl()
    store = ctx.file_svc._store
    real, count = store.transfer_object, {"n": 0}

    def pause_after_three(*a, **k):
        result = real(*a, **k)
        count["n"] += 1
        if count["n"] == 3:
            control.pause()
        return result

    monkeypatch.setattr(store, "transfer_object", pause_after_three)
    paused = ctx.transfer_svc.execute(record.id, control)
    monkeypatch.setattr(store, "transfer_object", real)

    assert paused.status == STATUS_PAUSED and paused.progress.files_done == 3
    assert paused.frozen == {"a": "active"} and _state(ctx, "a") == "readonly"

    cancelled = ctx.transfer_svc.cancel_idle(record.id)

    assert cancelled.status == STATUS_CANCELLED and cancelled.finished_at is not None
    assert _state(ctx, "a") == "online" and cancelled.frozen == {}
    assert all(store.get(sha) == data for sha, data in files.items())  # nothing lost


def test_resuming_finishes_what_a_pause_left(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 10)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    control = TransferControl()
    store = ctx.file_svc._store
    real, count = store.transfer_object, {"n": 0}

    def pause_after_four(*a, **k):
        result = real(*a, **k)
        count["n"] += 1
        if count["n"] == 4:
            control.pause()
        return result

    monkeypatch.setattr(store, "transfer_object", pause_after_four)
    ctx.transfer_svc.execute(record.id, control)
    monkeypatch.setattr(store, "transfer_object", real)

    ctx.transfer_svc.begin_resume(record.id)
    done = ctx.transfer_svc.execute(record.id)

    assert done.status == STATUS_COMPLETED
    assert done.progress.files_done == 10  # four, then six: each counted once
    assert _state(ctx, "a") == "online"
    assert all(store.get(sha) == data for sha, data in files.items())


def test_only_a_stopped_transfer_can_be_resumed(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    ctx.transfer_svc.execute(record.id)

    with pytest.raises(ValidationError, match="completed transfer can't be resumed"):
        ctx.transfer_svc.begin_resume(record.id)


# -- when the process dies ------------------------------------------------------------


def _age(ctx: AppContext, transfer_id: str, seconds: float) -> None:
    ctx._session.execute(
        update(StorageTransfer).values(
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=seconds)
        )
    )
    ctx.commit()


def test_a_running_transfer_that_stopped_saving_is_reported_interrupted(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 3)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    assert (
        ctx.transfer_svc.get(record.id).status == STATUS_RUNNING
    )  # fresh: genuinely running

    _age(ctx, record.id, 600)  # ...then nothing for ten minutes: the process is gone

    seen = ctx.transfer_svc.get(record.id)
    assert seen.status == STATUS_INTERRUPTED and seen.pause_reason == INTERRUPTED_REASON
    assert ctx.transfer_svc.active() is None


def test_an_interrupted_transfer_can_be_resumed_and_finishes(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 6)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    _age(ctx, record.id, 600)
    assert ctx.transfer_svc.get(record.id).status == STATUS_INTERRUPTED

    ctx.transfer_svc.begin_resume(record.id)
    done = ctx.transfer_svc.execute(record.id)

    assert done.status == STATUS_COMPLETED and done.progress.files_done == 6
    store = ctx.file_svc._store
    assert all(store.get(sha) == data for sha, data in files.items())


def test_a_second_process_sees_the_same_record(ctx: AppContext, tmp_path: Path) -> None:
    """The CLI and the server are different processes sharing one record."""
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 4)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    other = build_local_context(load_config())
    try:
        assert other.transfer_svc.get(record.id).status == STATUS_RUNNING
        ctx.transfer_svc.execute(record.id)
        assert other.transfer_svc.get(record.id).status == STATUS_COMPLETED
        assert [r.id for r in other.transfer_svc.recent()] == [record.id]
    finally:
        other.close()


# -- not alongside garbage collection ----------------------------------------------------


def test_garbage_collection_waits_while_a_transfer_runs(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    seen: list[str] = []

    def try_gc(p) -> None:
        try:
            ctx.gc_svc.run(dry_run=True, grace_days=0)
            seen.append("ran")
        except GCAlreadyRunningError as exc:
            seen.append(str(exc))

    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    ctx.transfer_svc.execute(record.id, on_progress=try_gc)

    assert seen and all("storage transfer is running" in s for s in seen)
    ctx.gc_svc.run(dry_run=True, grace_days=0)  # fine once it has finished


def test_a_transfer_will_not_start_while_garbage_collection_runs(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))

    with ctx.file_svc._store.gc_lock():
        with pytest.raises(ValidationError, match="garbage-collection pass is running"):
            ctx.transfer_svc.execute(record.id)

    assert ctx.transfer_svc.get(record.id).status == STATUS_RUNNING  # untouched


def test_volumes_ready_says_whether_a_paused_transfer_can_carry_on(
    ctx: AppContext, tmp_path: Path
) -> None:
    drives = _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    assert ctx.transfer_svc.volumes_ready(record)

    drives["b"].rename(drives["b"].with_name("b-unplugged"))
    assert not ctx.transfer_svc.volumes_ready(record)


def test_volume_state_can_be_set_and_is_validated(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a")

    ctx.store_svc.set_volume_state("a", "retired")
    assert load_config().store_config.volumes["a"].state == "retired"
    ctx.store_svc.set_volume_state("a", "active")

    with pytest.raises(ValidationError, match="must be one of"):
        ctx.store_svc.set_volume_state("a", "sleepy")
    with pytest.raises(NotFoundError):
        ctx.store_svc.set_volume_state("nope", "active")


def test_setting_a_state_does_not_overwrite_edits_made_meanwhile(
    ctx: AppContext, tmp_path: Path
) -> None:
    """A transfer runs for hours holding an old copy of the config; changing a
    volume's state must not write that stale copy back over later edits."""
    _volumes(ctx, tmp_path, "a")
    stale = ctx.store_svc

    other = build_local_context(load_config())
    try:
        other.store_svc.add_volume(
            "late", str(tmp_path / "mnt" / "late")
        )  # edited meanwhile
    finally:
        other.close()
    stale.set_volume_state("a", "readonly")

    assert "late" in load_config().store_config.volumes
    assert load_config().store_config.volumes["a"].state == "readonly"


# -- asking a running transfer to stop, from anywhere ---------------------------------------


def _slow(
    monkeypatch: pytest.MonkeyPatch, ctx: AppContext, seconds: float = 0.05
) -> None:
    import time

    store = ctx.file_svc._store
    real = store.transfer_object

    def slow(*a, **k):
        time.sleep(seconds)
        return real(*a, **k)

    monkeypatch.setattr(store, "transfer_object", slow)


def _ask_from_another_process(transfer_id: str, action: str) -> threading.Thread:
    """What the other process does: its own connection, asking once."""

    def ask() -> None:
        other = build_local_context(load_config())
        try:
            other.transfer_svc.request_control(transfer_id, action)
        finally:
            other.close()

    thread = threading.Thread(target=ask)
    thread.start()
    return thread


@pytest.mark.parametrize(
    "action, outcome", [("pause", STATUS_PAUSED), ("cancel", STATUS_CANCELLED)]
)
def test_a_pause_or_cancel_asked_for_by_another_process_is_obeyed(
    ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    outcome: str,
) -> None:
    """The web UI stopping a transfer a terminal is running, or the other way
    round: the request is saved, and the runner notices it as it saves progress."""
    _volumes(ctx, tmp_path, "a", "b")
    files = _put_on(ctx, "a", 40)
    _slow(monkeypatch, ctx)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    asked: list[threading.Thread] = []

    def from_elsewhere(p) -> None:
        if p.files_done >= 3 and not asked:
            asked.append(_ask_from_another_process(record.id, action))

    done = ctx.transfer_svc.execute(record.id, on_progress=from_elsewhere)
    asked[0].join(timeout=10)

    assert done.status == outcome and 3 <= done.progress.files_done < 40
    assert _state(ctx, "a") == ("online" if action == "cancel" else "readonly")
    store = ctx.file_svc._store
    assert all(store.get(sha) == data for sha, data in files.items())

    if action == "pause":
        # The request is spent: resuming isn't stopped again by it.
        ctx.transfer_svc.begin_resume(record.id)
        monkeypatch.setattr(
            store, "transfer_object", store.__class__.transfer_object.__get__(store)
        )
        assert ctx.transfer_svc.execute(record.id).status == STATUS_COMPLETED


def test_only_a_running_transfer_can_be_asked_to_stop(
    ctx: AppContext, tmp_path: Path
) -> None:
    _volumes(ctx, tmp_path, "a", "b")
    _put_on(ctx, "a", 2)
    record = ctx.transfer_svc.create(_drain(["a"], ["b"]))
    ctx.transfer_svc.execute(record.id)

    with pytest.raises(ValidationError, match="isn't running"):
        ctx.transfer_svc.request_control(record.id, "pause")
    with pytest.raises(ValidationError, match="pause or cancel"):
        ctx.transfer_svc.request_control(record.id, "explode")
