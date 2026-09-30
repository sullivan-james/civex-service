from __future__ import annotations

from pathlib import Path
from typing import AsyncIterable

from civex.domain.dtos import FileRef
from civex.repositories.protocols import FileObjectStore


class FileService:
    def __init__(
        self,
        store: FileObjectStore,
        remote_transport=None,  # LocalTransport | SSHTransport | None
    ) -> None:
        self._store = store
        self._remote = remote_transport

    def store(self, path: Path) -> FileRef:
        """Copy a file from disk into the object store in fixed-size chunks
        (never reading the whole file into memory)."""
        return self._store.put_path(path)

    def store_bytes(self, data: bytes, filename: str) -> FileRef:
        """Store raw bytes (e.g. from an HTTP upload) in the object store."""
        return self._store.put(data, filename)

    async def store_stream(
        self,
        chunks: AsyncIterable[bytes],
        filename: str,
        size_hint: int | None = None,
    ) -> FileRef:
        """Store a streamed upload without buffering the whole file in
        memory first. See VolumeAwareFileObjectStore.put_stream."""
        return await self._store.put_stream(chunks, filename, size_hint)

    def local_path(self, sha256: str) -> Path:
        """Path of the object's bytes on local disk, for streaming it out
        without loading it into memory. An object that only exists on the
        remote is fetched and cached first (the transports still move a
        blob as a single buffer, so that one-time fetch is whole-object)."""
        try:
            return self._store.object_path(sha256)
        except FileNotFoundError:
            if self._remote is None:
                raise
        self.retrieve(sha256)
        return self._store.object_path(sha256)

    def retrieve(self, sha256: str) -> bytes:
        """Return object bytes, fetching from the remote and caching locally if needed."""
        try:
            return self._store.get(sha256)
        except FileNotFoundError:
            pass
        if self._remote is None:
            raise FileNotFoundError(
                f"Object {sha256} not found locally and no remote is configured"
            )
        data = self._remote.get_object(sha256)
        self._store.put(
            data, sha256
        )  # cache locally; filename is sha256 (internal only)
        return data

    def exists(self, sha256: str) -> bool:
        if self._store.exists(sha256):
            return True
        if self._remote is not None:
            try:
                self._remote.get_object(sha256)
                return True
            except Exception:
                return False
        return False

    def object_path(self, sha256: str) -> Path:
        return self._store.object_path(sha256)
