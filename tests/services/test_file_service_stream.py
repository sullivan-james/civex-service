"""FileService.store_stream / VolumeAwareFileObjectStore.put_stream."""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from civex.context import AppContext
from civex.domain.exceptions import AllVolumesFull


async def _achunks(*parts: bytes):
    for p in parts:
        yield p


def test_store_stream_matches_store_bytes(ctx: AppContext) -> None:
    data = b"a" * 1024 + b"b" * 2048
    expected_sha = hashlib.sha256(data).hexdigest()

    ref = asyncio.run(
        ctx.file_svc.store_stream(_achunks(b"a" * 1024, b"b" * 2048), "f.bin")
    )

    assert ref.sha256 == expected_sha
    assert ref.size == len(data)
    assert ctx.file_svc.retrieve(ref.sha256) == data


def test_store_stream_is_idempotent_and_leaves_no_scratch_file(
    ctx: AppContext,
) -> None:
    data = b"x" * 4096
    ref1 = asyncio.run(ctx.file_svc.store_stream(_achunks(data), "f.bin"))
    ref2 = asyncio.run(ctx.file_svc.store_stream(_achunks(data), "f.bin"))

    assert ref1.sha256 == ref2.sha256
    objects = ctx.file_svc._store.list_objects()
    assert len(objects) == 1

    scratch = (
        ctx.file_svc._store._resolve_path(ctx.file_svc._store._cfg.volumes["default"])
        / ".tmp"
    )
    assert not scratch.exists() or not list(scratch.iterdir())


def test_store_stream_rejects_oversized_content_length_upfront(
    ctx: AppContext,
) -> None:
    ctx.store_svc.update_volume("default", allocated_gb=0.0000001)

    with pytest.raises(AllVolumesFull):
        asyncio.run(
            ctx.file_svc.store_stream(_achunks(b"y" * 1024), "f.bin", size_hint=1024)
        )
