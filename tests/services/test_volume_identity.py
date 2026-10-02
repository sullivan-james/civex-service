"""A volume is identified by an id kept in its VolumeConfig (config.toml, next
to its path) and repeated in a `.civex-volume` marker in its root, so an
unplugged drive is told apart from a different drive mounted at the same path."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from civex.config import StoreConfig, VolumeConfig, load_config
from civex.context import AppContext, build_local_context
from civex.domain.dtos import (
    VOLUME_OFFLINE,
    VOLUME_ONLINE,
    VOLUME_READONLY,
    VOLUME_WRONG_DRIVE,
)
from civex.domain.exceptions import ValidationError
from civex.repositories.local.file_store import VolumeAwareFileObjectStore

MARKER = ".civex-volume"


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


def _add(ctx: AppContext, name: str, path: Path, *, first: bool = True) -> None:
    """`civex store add NAME --path PATH`, then put it in the write queue."""
    ctx.store_svc.add_volume(name, str(path))
    queue = ctx.store_svc._config.store_config.volume_queue
    ctx.store_svc.set_queue([name, *queue] if first else [*queue, name])


def _id(ctx: AppContext, name: str) -> str | None:
    return ctx.store_svc._config.store_config.volumes[name].id


def test_add_gives_the_volume_an_identity_in_config_and_on_the_drive(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")

    ctx.store_svc.add_volume("ext", str(drive))

    vid = _id(ctx, "ext")
    assert vid is not None
    assert (drive / MARKER).read_text().strip() == vid
    assert load_config().store_config.volumes["ext"].id == vid  # persisted
    assert ctx.file_svc._store.volume_status("ext").volume_id == vid


def test_identity_survives_a_new_process(ctx: AppContext, tmp_path: Path) -> None:
    drive = _drive(tmp_path, "ext")
    ctx.store_svc.add_volume("ext", str(drive))

    again = build_local_context(load_config())
    try:
        assert again.file_svc._store.volume_status("ext").state == VOLUME_ONLINE
    finally:
        again.close()


def test_a_different_drive_at_the_same_path_is_the_wrong_drive(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    (drive / MARKER).write_text(str(uuid.uuid4()) + "\n")  # someone else's drive

    status = ctx.file_svc._store.volume_status("ext")

    assert status.state == VOLUME_WRONG_DRIVE
    assert not status.reachable
    assert "expected volume 'ext'" in status.reason
    assert "adopt it" in status.fix


def test_an_unmarked_drive_where_a_volume_is_expected_is_the_wrong_drive(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    (drive / MARKER).unlink()  # e.g. an empty mount point

    status = ctx.file_svc._store.volume_status("ext")

    assert status.state == VOLUME_WRONG_DRIVE
    assert "no volume marker" in status.reason


def test_writes_skip_a_wrong_drive_and_land_on_the_next_volume(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    store = ctx.file_svc._store
    assert store.put(b"first", "first.txt").volume == "ext"
    (drive / MARKER).write_text(str(uuid.uuid4()) + "\n")

    assert store.put(b"second", "second.txt").volume == "default"
    assert "second" not in (drive / "manifest.jsonl").read_text()


def test_reconcile_never_touches_the_rows_of_a_wrong_drive(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    store = ctx.file_svc._store
    store.put(b"one", "1.txt")
    store.put(b"two", "2.txt")
    # Swap the real drive for a blank one at the same path.
    for entry in drive.iterdir():
        if entry.is_dir():
            for blob in entry.iterdir():
                blob.unlink()
            entry.rmdir()
        else:
            entry.unlink()

    store.reconcile_inventory()

    assert store._civex_used("ext") == len(b"one") + len(b"two")


def test_adopt_rewrites_the_marker_and_persists(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    vid = _id(ctx, "ext")
    (drive / MARKER).unlink()
    assert ctx.file_svc._store.volume_status("ext").state == VOLUME_WRONG_DRIVE

    status = ctx.store_svc.adopt_volume("ext")

    assert status.state == VOLUME_ONLINE
    assert (drive / MARKER).read_text().strip() == vid


def test_adopt_identifies_a_volume_that_predates_identities(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    sc = ctx.store_svc._config.store_config
    sc.volumes["ext"] = VolumeConfig(name="ext", path=str(drive))  # no id
    sc.volume_queue.insert(0, "ext")
    store = ctx.file_svc._store

    # Used by path alone, and a write does not assign an identity (an upload
    # must not rewrite config.toml).
    assert store.put(b"hello", "hello.txt").volume == "ext"
    assert not (drive / MARKER).exists() and sc.volumes["ext"].id is None

    ctx.store_svc.adopt_volume("ext")

    assert sc.volumes["ext"].id == (drive / MARKER).read_text().strip()
    assert load_config().store_config.volumes["ext"].id == sc.volumes["ext"].id


def test_a_marker_no_volume_has_is_kept_when_the_drive_is_added(
    ctx: AppContext, tmp_path: Path
) -> None:
    """A drive brought from another project, or a lost config: its own id is
    kept, so the identity written on it stays true."""
    drive = _drive(tmp_path, "ext")
    marker_id = str(uuid.uuid4())
    (drive / MARKER).write_text(marker_id + "\n")

    ctx.store_svc.add_volume("ext", str(drive))

    assert _id(ctx, "ext") == marker_id


def test_adding_the_folder_of_another_volume_is_refused(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "a")
    ctx.store_svc.add_volume("a", str(drive))
    marker_before = (drive / MARKER).read_text()

    with pytest.raises(ValidationError, match="already the volume 'a'"):
        ctx.store_svc.add_volume("b", str(drive))

    assert "b" not in ctx.store_svc._config.store_config.volumes
    assert "b" not in load_config().store_config.volumes
    assert (drive / MARKER).read_text() == marker_before


def test_a_removed_drive_is_recognised_when_added_back(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    ctx.store_svc.add_volume("ext", str(drive))
    first_id = _id(ctx, "ext")

    ctx.store_svc.remove_volume("ext")
    ctx.store_svc.add_volume("ext", str(drive))

    assert _id(ctx, "ext") == first_id


def test_a_volume_inside_the_project_is_never_locked_out(ctx: AppContext) -> None:
    store = ctx.file_svc._store
    ctx.store_svc.adopt_volume("default")
    root = store._resolve_path(store._cfg.volumes["default"])
    assert (root / MARKER).exists()

    (root / MARKER).unlink()

    assert store.volume_status("default").state == VOLUME_ONLINE
    assert store.put(b"two", "2.txt").volume == "default"


def test_readonly_volumes_are_readable_but_not_written(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    store = ctx.file_svc._store
    kept = store.put(b"keep me", "keep.txt")
    store._cfg.volumes["ext"].state = "readonly"

    status = store.volume_status("ext")

    assert status.state == VOLUME_READONLY and status.reachable and not status.writable
    assert store.get(kept.sha256) == b"keep me"
    assert store.put(b"new", "new.txt").volume == "default"


def test_identity_is_checked_without_a_database_too(tmp_path: Path) -> None:
    drive = _drive(tmp_path, "ext")
    vid = str(uuid.uuid4())
    config = StoreConfig(
        volumes={"ext": VolumeConfig(name="ext", path=str(drive), id=vid)},
        volume_queue=["ext"],
    )
    store = VolumeAwareFileObjectStore(config, tmp_path)
    assert store.volume_status("ext").state == VOLUME_WRONG_DRIVE  # no marker yet

    store.adopt_volume("ext")

    assert store.volume_status("ext").state == VOLUME_ONLINE
    assert (drive / MARKER).read_text().strip() == vid


def test_volume_identity_round_trips_through_config_toml(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    ctx.store_svc.add_volume("ext", str(drive))
    ctx.file_svc._store._cfg.volumes["ext"].state = "retired"
    from civex.config import save_config

    save_config(ctx.store_svc._config)

    reloaded = load_config().store_config.volumes["ext"]
    assert reloaded.id == _id(ctx, "ext") and reloaded.state == "retired"
    toml = (Path.cwd() / "_civex" / "config.toml").read_text()
    assert "[store.volumes.ext]" in toml and f'id = "{reloaded.id}"' in toml


def test_a_default_project_config_stays_minimal(ctx: AppContext) -> None:
    toml = (Path.cwd() / "_civex" / "config.toml").read_text()
    assert "[store" not in toml


def test_stats_carry_state_reason_and_fix(ctx: AppContext, tmp_path: Path) -> None:
    drive = _drive(tmp_path, "ext")
    ctx.store_svc.add_volume("ext", str(drive))
    drive.rename(drive.with_name("unplugged"))

    stats = {v["name"]: v for v in ctx.store_svc.volume_stats()}

    assert (
        stats["default"]["state"] == VOLUME_ONLINE and stats["default"]["reason"] == ""
    )
    assert stats["ext"]["state"] == VOLUME_OFFLINE
    assert stats["ext"]["available"] is False
    assert "path missing" in stats["ext"]["reason"]
    assert "change the volume's path" in stats["ext"]["fix"]
