"""FileService + VolumeAwareFileObjectStore: content-addressed dedup, object
path resolution, and volume-queue fallback (see CLAUDE.md "Data model" —
file bytes live in _civex/objects/<sha256[:2]>/<sha256[2:]>).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from civex.config import StoreConfig, VolumeConfig
from civex.context import AppContext
from civex.domain.exceptions import VolumeUnavailableError
from civex.repositories.local.file_store import VolumeAwareFileObjectStore


def test_store_bytes_is_content_addressed(ctx: AppContext) -> None:
    ref = ctx.file_svc.store_bytes(b"hello world", "greeting.txt")
    assert ref.filename == "greeting.txt"
    assert ref.size == len(b"hello world")
    assert ctx.file_svc.exists(ref.sha256)


def test_storing_identical_bytes_twice_is_idempotent(ctx: AppContext) -> None:
    ref1 = ctx.file_svc.store_bytes(b"same content", "a.txt")
    ref2 = ctx.file_svc.store_bytes(b"same content", "b.txt")
    assert ref1.sha256 == ref2.sha256
    # Only one copy of the bytes is stored — same object path either way.
    assert ctx.file_svc.object_path(ref1.sha256) == ctx.file_svc.object_path(
        ref2.sha256
    )


def test_retrieve_roundtrips_bytes(ctx: AppContext) -> None:
    ref = ctx.file_svc.store_bytes(b"round trip me", "f.txt")
    assert ctx.file_svc.retrieve(ref.sha256) == b"round trip me"


def test_retrieve_missing_object_without_remote_raises(ctx: AppContext) -> None:
    with pytest.raises(FileNotFoundError):
        ctx.file_svc.retrieve("0" * 64)


def test_object_path_uses_sha256_prefix_layout(ctx: AppContext) -> None:
    ref = ctx.file_svc.store_bytes(b"layout check", "f.txt")
    path = ctx.file_svc.object_path(ref.sha256)
    assert path.parent.name == ref.sha256[:2]
    assert path.name == ref.sha256[2:]


def test_volume_queue_falls_back_when_first_volume_is_full(tmp_path: Path) -> None:
    full_vol = VolumeConfig(name="full", path="full", allocated_gb=0)
    spare_vol = VolumeConfig(name="spare", path="spare", allocated_gb=None)
    config = StoreConfig(
        volumes={"full": full_vol, "spare": spare_vol}, volume_queue=["full", "spare"]
    )
    store = VolumeAwareFileObjectStore(config, tmp_path)

    ref = store.put(b"overflow data", "f.txt")
    assert ref.volume == "spare"
    assert store.exists(ref.sha256)


def test_put_appends_a_manifest_line(tmp_path: Path) -> None:
    vol = VolumeConfig(name="default", path="objects")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    store = VolumeAwareFileObjectStore(config, tmp_path)

    ref = store.put(b"manifest me", "notes.txt")

    manifest_path = tmp_path / "objects" / "manifest.jsonl"
    lines = manifest_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry == {"sha256": ref.sha256, "filename": "notes.txt", "size": ref.size}


def test_storing_identical_bytes_twice_appends_manifest_once(tmp_path: Path) -> None:
    vol = VolumeConfig(name="default", path="objects")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    store = VolumeAwareFileObjectStore(config, tmp_path)

    store.put(b"same content", "a.txt")
    store.put(b"same content", "b.txt")

    manifest_path = tmp_path / "objects" / "manifest.jsonl"
    lines = manifest_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["filename"] == "a.txt"


def test_put_leaves_no_partial_object_when_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """A write that fails partway (e.g. ENOSPC) must never leave a
    truncated/corrupt blob at the final content-addressed path -- put()
    writes to a scratch file and renames into place, same as put_stream()."""
    vol = VolumeConfig(name="default", path="objects")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    store = VolumeAwareFileObjectStore(config, tmp_path)

    def failing_write_bytes(self, data):
        raise OSError("disk exploded mid-write")

    monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)

    with pytest.raises(VolumeUnavailableError):
        store.put(b"doomed content", "f.txt")

    objects_dir = tmp_path / "objects"
    leftover_files = [
        p for p in objects_dir.rglob("*") if p.is_file() and p.name != "manifest.jsonl"
    ]
    assert leftover_files == [], (
        f"no object or scratch file should remain: {leftover_files}"
    )


def test_put_succeeds_even_if_manifest_append_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """The manifest is display metadata only -- a failure writing it must
    not fail an upload whose bytes are already durably stored."""
    vol = VolumeConfig(name="default", path="objects")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    store = VolumeAwareFileObjectStore(config, tmp_path)

    def failing_append(*args, **kwargs):
        raise OSError("disk full writing manifest")

    monkeypatch.setattr(store, "_append_manifest", failing_append)

    ref = store.put(b"stored despite manifest failure", "f.txt")
    assert store.exists(ref.sha256)


def test_manifest_is_per_volume(tmp_path: Path) -> None:
    first = VolumeConfig(name="first", path="first")
    second = VolumeConfig(name="second", path="second")
    config = StoreConfig(
        volumes={"first": first, "second": second}, volume_queue=["first"]
    )
    store = VolumeAwareFileObjectStore(config, tmp_path)

    store.put(b"only in first", "f.txt")

    assert (tmp_path / "first" / "manifest.jsonl").exists()
    assert not (tmp_path / "second" / "manifest.jsonl").exists()


def test_put_path_copies_in_chunks_and_dedupes(tmp_path, monkeypatch) -> None:
    import civex.repositories.local.file_store as fs

    monkeypatch.setattr(fs, "_COPY_CHUNK", 7)  # force many chunks
    vol = VolumeConfig(name="default", path="vol")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    store = VolumeAwareFileObjectStore(config, tmp_path)
    src = tmp_path / "big.bin"
    payload = bytes(range(256)) * 10
    src.write_bytes(payload)

    ref = store.put_path(src)
    assert ref.size == len(payload)
    assert store.get(ref.sha256) == payload
    assert store.put_path(src).sha256 == ref.sha256
    assert not list((tmp_path / "vol" / ".tmp").glob("*.part"))
