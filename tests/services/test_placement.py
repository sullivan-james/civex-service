"""Placement decides where *new* content goes. It must never cause content that
already exists to be stored again: dedup always wins over a home volume."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from civex.config import PlacementConfig
from civex.context import AppContext
from civex.db.models import StoredObject
from civex.domain.exceptions import AllVolumesFull
from civex.repositories.local.file_store import VolumeAwareFileObjectStore


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


def _add(ctx: AppContext, name: str, path: Path, *, in_queue: bool = False) -> None:
    """`civex store add`, optionally also appended to the general write queue."""
    ctx.store_svc.add_volume(name, str(path))
    if in_queue:
        queue = ctx.store_svc._config.store_config.volume_queue
        ctx.store_svc.set_queue([*queue, name])


def _home(ctx: AppContext, volume: str, on_unavailable: str = "spill") -> str:
    """A collection id homed on `volume`."""
    cid = str(uuid.uuid4())
    ctx.file_svc._store._cfg.placement[cid] = PlacementConfig(volume, on_unavailable)
    return cid


def _copies(store: VolumeAwareFileObjectStore, sha256: str) -> list[str]:
    return [
        name
        for name, vc in store._cfg.volumes.items()
        if (store._resolve_path(vc) / sha256[:2] / sha256[2:]).exists()
    ]


def _rows(store: VolumeAwareFileObjectStore) -> int:
    return store._session.execute(
        select(func.count()).select_from(StoredObject)
    ).scalar_one()


def _unplug(drive: Path) -> Path:
    unplugged = drive.with_name(drive.name + "-unplugged")
    drive.rename(unplugged)
    return unplugged


# -- where new content goes ---------------------------------------------------


def test_new_content_goes_to_the_collections_home_not_the_queue(
    ctx: AppContext, tmp_path: Path
) -> None:
    _add(ctx, "archive", _drive(tmp_path, "archive"))  # not in the write queue
    store = ctx.file_svc._store
    cid = _home(ctx, "archive")

    assert store.put(b"for the archive", "a.txt", cid).volume == "archive"
    assert store.put(b"for anyone", "b.txt").volume == "default"
    assert (
        store.put(b"unknown collection", "c.txt", str(uuid.uuid4())).volume == "default"
    )


def test_put_path_and_put_stream_honour_the_home_too(
    ctx: AppContext, tmp_path: Path
) -> None:
    _add(ctx, "archive", _drive(tmp_path, "archive"))
    store = ctx.file_svc._store
    cid = _home(ctx, "archive")
    src = tmp_path / "src.bin"
    src.write_bytes(b"from disk")

    async def chunks():
        yield b"streamed"

    assert store.put_path(src, collection_id=cid).volume == "archive"
    assert (
        asyncio.run(store.put_stream(chunks(), "s.bin", collection_id=cid)).volume
        == "archive"
    )


def test_an_unplugged_home_spills_to_the_queue_by_default(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "archive")
    _add(ctx, "archive", drive)
    store = ctx.file_svc._store
    cid = _home(ctx, "archive")
    _unplug(drive)

    assert store.put(b"still accepted", "a.txt", cid).volume == "default"


def test_a_collection_set_to_fail_is_not_written_anywhere_else(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "archive")
    _add(ctx, "archive", drive)
    store = ctx.file_svc._store
    cid = _home(ctx, "archive", "fail")
    _unplug(drive)

    with pytest.raises(AllVolumesFull, match="home volume 'archive'.*fail"):
        store.put(b"must not spill", "a.txt", cid)

    assert (
        _copies(store, __import__("hashlib").sha256(b"must not spill").hexdigest())
        == []
    )


def test_a_full_home_spills(ctx: AppContext, tmp_path: Path) -> None:
    _add(ctx, "archive", _drive(tmp_path, "archive"))
    store = ctx.file_svc._store
    store._cfg.volumes["archive"].allocated_gb = 0
    cid = _home(ctx, "archive")

    assert store.put(b"no room at home", "a.txt", cid).volume == "default"


def test_a_placement_naming_a_removed_volume_is_ignored(
    ctx: AppContext, tmp_path: Path
) -> None:
    store = ctx.file_svc._store
    cid = _home(ctx, "gone")

    assert store.put(b"hello", "a.txt", cid).volume == "default"


# -- dedup always wins --------------------------------------------------------


def test_existing_content_is_reused_not_copied_to_the_home(
    ctx: AppContext, tmp_path: Path
) -> None:
    _add(ctx, "archive", _drive(tmp_path, "archive"))
    store = ctx.file_svc._store
    first = store.put(b"already here", "first.txt")  # general queue -> default
    cid = _home(ctx, "archive")

    again = store.put(b"already here", "second.txt", cid)

    assert again.volume == first.volume == "default"
    assert _copies(store, first.sha256) == ["default"]
    assert _rows(store) == 1


def test_one_blob_shared_by_collections_with_different_homes_is_stored_once(
    ctx: AppContext, tmp_path: Path
) -> None:
    _add(ctx, "a", _drive(tmp_path, "a"))
    _add(ctx, "b", _drive(tmp_path, "b"))
    store = ctx.file_svc._store
    in_a, in_b = _home(ctx, "a"), _home(ctx, "b")

    one = store.put(b"shared bytes", "x.dat", in_a)
    two = store.put(b"shared bytes", "x.dat", in_b)

    assert one.volume == two.volume == "a"
    assert _copies(store, one.sha256) == ["a"]


def test_put_path_and_put_stream_dedup_against_other_volumes(
    ctx: AppContext, tmp_path: Path
) -> None:
    _add(ctx, "archive", _drive(tmp_path, "archive"))
    store = ctx.file_svc._store
    first = store.put(b"same content", "one.txt")
    cid = _home(ctx, "archive")
    src = tmp_path / "again.bin"
    src.write_bytes(b"same content")

    async def chunks():
        yield b"same content"

    assert store.put_path(src, collection_id=cid).volume == first.volume
    assert (
        asyncio.run(store.put_stream(chunks(), "s", collection_id=cid)).volume
        == first.volume
    )
    assert _copies(store, first.sha256) == [first.volume]
    # The duplicate's scratch copy is discarded, not left behind.
    for vc in store._cfg.volumes.values():
        scratch = store._resolve_path(vc) / ".tmp"
        assert not scratch.exists() or not list(scratch.glob("*.part"))


def test_content_on_an_unplugged_volume_is_not_copied_elsewhere(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive, in_queue=True)
    ctx.store_svc.set_queue(["ext", "default"])
    store = ctx.file_svc._store
    first = store.put(b"lives on the drive", "a.txt")
    assert first.volume == "ext"
    _unplug(drive)

    again = store.put(b"lives on the drive", "b.txt")
    src = tmp_path / "again.bin"
    src.write_bytes(b"lives on the drive")

    async def chunks():
        yield b"lives on the drive"

    assert again.volume == "ext"
    assert store.put_path(src).volume == "ext"
    assert asyncio.run(store.put_stream(chunks(), "c.txt")).volume == "ext"
    assert _copies(store, first.sha256) == []  # nothing written to `default`
    assert _rows(store) == 1


def test_a_stale_inventory_row_on_a_reachable_volume_does_not_suppress_the_write(
    ctx: AppContext, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "ext")
    _add(ctx, "ext", drive)
    ctx.store_svc.set_queue(["ext", "default"])
    store = ctx.file_svc._store
    first = store.put(b"deleted behind our back", "a.txt")
    store._object_path(first.sha256, "ext").unlink()  # row remains

    again = store.put(b"deleted behind our back", "a.txt")

    assert _copies(store, again.sha256) == [again.volume]
    assert store.get(again.sha256) == b"deleted behind our back"


def test_without_a_database_there_is_no_offline_dedup(tmp_path: Path) -> None:
    """The inventory is what knows a blob is on an unplugged drive, so a store
    with no session can only dedup against volumes it can see."""
    from civex.config import StoreConfig, VolumeConfig

    drive = _drive(tmp_path, "ext")
    config = StoreConfig(
        volumes={
            "ext": VolumeConfig(name="ext", path=str(drive)),
            "local": VolumeConfig(name="local", path="objects"),
        },
        volume_queue=["ext", "local"],
    )
    store = VolumeAwareFileObjectStore(config, tmp_path)
    store.put(b"x", "x")
    _unplug(drive)

    assert store.put(b"x", "x").volume == "local"


def test_placement_round_trips_through_config_toml_keyed_by_collection_id(
    ctx: AppContext, tmp_path: Path
) -> None:
    from civex.config import load_config, save_config

    _add(ctx, "archive", _drive(tmp_path, "archive"))
    cid = str(uuid.uuid4())
    sc = ctx.store_svc._config.store_config
    sc.placement[cid] = PlacementConfig("archive", "fail")
    sc.placement[str(uuid.uuid4())] = PlacementConfig("archive")

    save_config(ctx.store_svc._config)

    reloaded = load_config().store_config.placement
    assert reloaded[cid] == PlacementConfig("archive", "fail")
    assert len(reloaded) == 2
    toml = (Path.cwd() / "_civex" / "config.toml").read_text()
    assert f"[store.placement.{cid}]" in toml and 'on_unavailable = "fail"' in toml
    assert toml.count("on_unavailable") == 1  # "spill" is the default: not written
