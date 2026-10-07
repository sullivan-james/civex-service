"""A file may be on several drives (a copy on each home that keeps it). The
inventory is the one answer to where: reads, deletes, clean-up and the counts
of a collection's files all go by its copies."""

from __future__ import annotations

from pathlib import Path

import pytest

from civex.context import AppContext

from .test_placement import _add, _drive, _home, _unplug


@pytest.fixture()
def two_homes(
    ctx: AppContext, tmp_path: Path, make_schema, make_collection, make_record
):
    """One file used by two collections, each homed on its own drive."""
    drives = {name: _drive(tmp_path, name) for name in ("a", "b")}
    for name, path in drives.items():
        _add(ctx, name, path)
    make_schema("doc", fields=[("scan", "file")])
    one, two = make_collection("one"), make_collection("two")
    ctx.store_svc.set_placement(str(one.id), "a")
    ctx.store_svc.set_placement(str(two.id), "b")
    ref = ctx.file_svc.store_bytes(b"shared " * 30, "shared.txt", str(one.id))
    ctx.file_svc.store_bytes(b"shared " * 30, "shared.txt", str(two.id))
    make_record("one", "doc", {"scan": ref.to_dict()})
    make_record("two", "doc", {"scan": ref.to_dict()})
    ctx.commit()
    return drives, ref, one, two


def test_each_home_holds_the_file_and_reads_use_one_that_is_plugged_in(
    ctx: AppContext, two_homes
) -> None:
    drives, ref, *_ = two_homes
    store = ctx.file_svc._store
    assert sorted(v for v, _ in store.copies([ref.sha256])[ref.sha256]) == ["a", "b"]

    _unplug(drives["a"])
    assert store.get(ref.sha256) == b"shared " * 30  # from b
    assert store.locate_volumes([ref.sha256]) == {ref.sha256: "b"}
    copies = {c.volume: c.present for c in store.copies_of(ref.sha256)}
    assert copies == {"a": None, "b": True}  # a: can't be looked at now


def test_reads_look_only_where_the_inventory_says(ctx: AppContext, tmp_path) -> None:
    """A copy the inventory doesn't record is not searched for while it
    records others: the drives aren't walked on a read."""
    _add(ctx, "a", _drive(tmp_path, "a"))
    _add(ctx, "b", stray := _drive(tmp_path, "b"))
    store = ctx.file_svc._store
    ref = store.put(b"recorded on a", "x.txt", _home(ctx, "a"))
    (stray / ref.sha256[:2]).mkdir()
    (stray / ref.sha256[:2] / ref.sha256[2:]).write_bytes(b"recorded on a")
    _unplug(tmp_path / "mnt" / "a")

    with pytest.raises(FileNotFoundError):
        store.get(ref.sha256)
    store.reconcile_inventory()  # clean-up records what is on disk
    assert store.get(ref.sha256) == b"recorded on a"


def test_deleting_a_file_removes_every_copy_it_can_reach(
    ctx: AppContext, two_homes
) -> None:
    drives, ref, *_ = two_homes
    store = ctx.file_svc._store
    unplugged = _unplug(drives["b"])

    assert store.delete(ref.sha256)
    assert [v for v, _ in store.copies([ref.sha256])[ref.sha256]] == ["b"]
    unplugged.rename(drives["b"])  # its copy is still there, and recorded
    assert store.get(ref.sha256) == b"shared " * 30


def test_clean_up_keeps_every_copy_of_a_file_in_use_and_removes_unused_ones(
    ctx: AppContext, two_homes
) -> None:
    _, ref, *_ = two_homes
    store = ctx.file_svc._store
    unused = store.put(b"nobody uses this", "u.txt")
    store.put(b"nobody uses this", "u.txt", _home(ctx, "a"))  # a second copy
    ctx.commit()

    ctx.gc_svc.run(dry_run=False, grace_days=0)
    ctx.commit()

    assert len(store.copies([ref.sha256])[ref.sha256]) == 2
    assert unused.sha256 not in store.copies([unused.sha256])


def test_a_collection_counts_a_file_once_on_its_own_home(
    ctx: AppContext, two_homes
) -> None:
    _, _, one, two = two_homes
    storage = ctx.file_info_svc.all_collection_storage([str(one.id), str(two.id)])
    by = {cid: [(v.volume, v.files) for v in s.volumes] for cid, s in storage.items()}
    assert by == {str(one.id): [("a", 1)], str(two.id): [("b", 1)]}
