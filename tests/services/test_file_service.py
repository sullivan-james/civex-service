"""FileService + VolumeAwareFileObjectStore: content-addressed dedup, object
path resolution, and volume-queue fallback (see CLAUDE.md "Data model" —
file bytes live in _civex/objects/<sha256[:2]>/<sha256[2:]>).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from civex.config import StoreConfig, VolumeConfig
from civex.context import AppContext
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
    assert ctx.file_svc.object_path(ref1.sha256) == ctx.file_svc.object_path(ref2.sha256)


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
    config = StoreConfig(volumes={"full": full_vol, "spare": spare_vol}, volume_queue=["full", "spare"])
    store = VolumeAwareFileObjectStore(config, tmp_path)

    ref = store.put(b"overflow data", "f.txt")
    assert ref.volume == "spare"
    assert store.exists(ref.sha256)
