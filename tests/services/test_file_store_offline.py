"""A volume that is not available is offline, not empty: it is skipped on
write, never created on demand, and its inventory is left alone."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from civex.config import StoreConfig, VolumeConfig
from civex.context import AppContext
from civex.domain.exceptions import AllVolumesFull
from civex.repositories.local.file_store import VolumeAwareFileObjectStore


def _store(tmp_path: Path, *volumes: VolumeConfig) -> VolumeAwareFileObjectStore:
    config = StoreConfig(
        volumes={v.name: v for v in volumes}, volume_queue=[v.name for v in volumes]
    )
    return VolumeAwareFileObjectStore(config, tmp_path)


def _external(tmp_path: Path, name: str = "ext") -> tuple[VolumeConfig, Path]:
    path = tmp_path / "mnt" / name
    return VolumeConfig(name=name, path=str(path)), path


def test_put_skips_an_offline_absolute_volume_without_creating_it(
    tmp_path: Path,
) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext, VolumeConfig(name="local", path="objects"))

    ref = store.put(b"hello", "hello.txt")

    assert ref.volume == "local"
    assert not ext_path.exists()
    assert not ext_path.parent.exists()


def test_put_with_every_volume_offline_says_why_and_creates_nothing(
    tmp_path: Path,
) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext)

    with pytest.raises(AllVolumesFull, match="offline"):
        store.put(b"hello", "hello.txt")

    assert not ext_path.parent.exists()


def test_put_path_and_put_stream_skip_an_offline_volume(tmp_path: Path) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext, VolumeConfig(name="local", path="objects"))
    src = tmp_path / "src.bin"
    src.write_bytes(b"from disk")

    assert store.put_path(src).volume == "local"

    async def chunks():
        yield b"streamed"

    assert asyncio.run(store.put_stream(chunks(), "s.bin")).volume == "local"
    assert not ext_path.parent.exists()


def test_a_volume_that_vanishes_mid_write_is_not_recreated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext)
    # The volume passed the availability gate, then was unplugged.
    monkeypatch.setattr(store, "_can_write", lambda volume, size: (True, ""))

    with pytest.raises(AllVolumesFull):
        store.put(b"hello", "hello.txt")

    assert not ext_path.parent.exists()


def test_relative_volumes_inside_the_project_are_still_created_on_demand(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, VolumeConfig(name="local", path="deep/objects"))

    store.put(b"hello", "hello.txt")

    assert (tmp_path / "deep" / "objects").is_dir()


def test_a_relative_path_escaping_the_project_is_treated_as_external(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    vc = VolumeConfig(name="out", path="../drive/objects")
    store = VolumeAwareFileObjectStore(
        StoreConfig(volumes={"out": vc}, volume_queue=["out"]), project
    )

    with pytest.raises(AllVolumesFull, match="offline"):
        store.put(b"hello", "hello.txt")

    assert not (tmp_path / "drive").exists()


def test_volume_stats_reports_offline_without_creating_the_path(
    tmp_path: Path,
) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext)

    [stats] = store.volume_stats()

    assert stats["available"] is False
    assert not ext_path.parent.exists()


# -- inventory ---------------------------------------------------------------


def _with_external_volume(ctx: AppContext, tmp_path: Path) -> tuple:
    """The ctx store with a second, absolute volume first in the queue."""
    store = ctx.file_svc._store
    ext, ext_path = _external(tmp_path)
    ext_path.mkdir(parents=True)
    store._cfg.volumes["ext"] = ext
    store._cfg.volume_queue.insert(0, "ext")
    return store, ext_path


def _inventory_rows(store: VolumeAwareFileObjectStore, volume: str) -> int:
    from sqlalchemy import func, select

    from civex.db.models import StoredObject

    return store._session.execute(
        select(func.count())
        .select_from(StoredObject)
        .where(StoredObject.volume == volume)
    ).scalar_one()


def test_reconcile_leaves_an_offline_volumes_rows_alone(
    ctx: AppContext, tmp_path: Path
) -> None:
    store, ext_path = _with_external_volume(ctx, tmp_path)
    store.put(b"on the drive", "a.txt")
    assert _inventory_rows(store, "ext") == 1

    unplugged = ext_path.with_name("ext-unplugged")
    ext_path.rename(unplugged)
    assert not store.volume_available("ext")
    store.reconcile_inventory()
    assert _inventory_rows(store, "ext") == 1

    unplugged.rename(ext_path)
    store.reconcile_inventory()
    assert _inventory_rows(store, "ext") == 1


def test_gc_with_a_volume_offline_keeps_its_inventory(
    ctx: AppContext, tmp_path: Path
) -> None:
    store, ext_path = _with_external_volume(ctx, tmp_path)
    store.put(b"on the drive", "a.txt")
    ext_path.rename(ext_path.with_name("ext-unplugged"))

    report = ctx.gc_svc.run(dry_run=False, grace_days=0)

    assert report.errors == []
    assert _inventory_rows(store, "ext") == 1
    assert store._civex_used("ext") == len(b"on the drive")


def test_reconcile_does_not_mass_drop_rows_of_an_unidentified_empty_mount_point(
    ctx: AppContext, tmp_path: Path
) -> None:
    """For a volume with no identity (one that predates them), an empty root
    that this store never wrote to is not proof the rows are stale."""
    store, ext_path = _with_external_volume(ctx, tmp_path)
    store.put(b"one", "1.txt")
    store.put(b"two", "2.txt")
    # The volume path *is* the mount point: unmounted, it is an empty directory.
    shutil.rmtree(ext_path)
    ext_path.mkdir()
    assert store.volume_available("ext")

    store.reconcile_inventory()

    assert _inventory_rows(store, "ext") == 2


def test_reconcile_still_drops_a_row_whose_blob_is_gone_on_an_online_volume(
    ctx: AppContext, tmp_path: Path
) -> None:
    store, _ = _with_external_volume(ctx, tmp_path)
    gone = store.put(b"one", "1.txt")
    store.put(b"two", "2.txt")
    store._object_path(gone.sha256, "ext").unlink()

    assert store.reconcile_inventory()["removed"] == 1
    assert _inventory_rows(store, "ext") == 1


def test_a_volume_emptied_after_use_is_still_reconciled(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Drift healing: blobs deleted by hand from a volume that has been used
    (so its manifest exists) are dropped from the inventory."""
    store, ext_path = _with_external_volume(ctx, tmp_path)
    ref = store.put(b"one", "1.txt")
    store._object_path(ref.sha256, "ext").unlink()

    assert store.reconcile_inventory()["removed"] == 1
    assert _inventory_rows(store, "ext") == 0


def test_volume_status_gives_one_answer_with_a_reason(tmp_path: Path) -> None:
    ext, ext_path = _external(tmp_path)
    store = _store(tmp_path, ext)

    missing = store.volume_status("ext")
    assert not missing.reachable and "path missing" in missing.reason
    assert missing.fix

    ext_path.parent.mkdir()
    ext_path.write_text("a file, not a directory")
    assert "not a directory" in store.volume_status("ext").reason

    ext_path.unlink()
    ext_path.mkdir()
    assert store.volume_status("ext").writable

    assert store.volume_status("nope").reason == "volume not configured"
    assert store.volume_stats()[0]["reason"] == ""
