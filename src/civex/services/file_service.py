from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import AsyncIterable

from civex.domain import permissions
from civex.domain.dtos import DirectUpload, FileRef, UploadedPart
from civex.domain.permissions import EVERYTHING, Permissions
from civex.repositories.protocols import ObjectStore, VolumeStore

_CHUNK = 1024 * 1024


class FileService:
    def __init__(
        self,
        store: ObjectStore,
        volumes: VolumeStore | None = None,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        # `volumes` is the same store when files are on drives on this machine
        # (where a file has a path on disk); None when they are in a bucket.
        self._store = store
        self._volumes = volumes
        self._permissions = permissions

    # `collection_id` (here and below) is the id of the collection the file is
    # for. It only steers where new content is written -- see
    # VolumeAwareFileObjectStore._write_candidates -- and never causes content
    # that already exists to be stored again.

    def store(self, path: Path, collection_id: str | None = None) -> FileRef:
        """Copy a file from disk into the object store in fixed-size chunks
        (never reading the whole file into memory)."""
        self._permissions.require(permissions.MANAGE_FILES)
        return self._store.put_path(path, collection_id=collection_id)

    def store_bytes(
        self, data: bytes, filename: str, collection_id: str | None = None
    ) -> FileRef:
        """Store raw bytes (e.g. from an HTTP upload) in the object store."""
        self._permissions.require(permissions.MANAGE_FILES)
        return self._store.put(data, filename, collection_id)

    async def store_stream(
        self,
        chunks: AsyncIterable[bytes],
        filename: str,
        size_hint: int | None = None,
        collection_id: str | None = None,
    ) -> FileRef:
        """Store a streamed upload without buffering the whole file in
        memory first. See VolumeAwareFileObjectStore.put_stream."""
        self._permissions.require(permissions.MANAGE_FILES)
        return await self._store.put_stream(chunks, filename, size_hint, collection_id)

    def discard(self, sha256: str) -> bool:
        """Remove content just stored that turned out not to be wanted: a file
        taken in for a record save that was then refused. Every reachable copy
        goes (there is one, the one just written). The caller must know the
        content was new, since this doesn't ask what else uses it; anything
        it misses is left to the clean-up (`GCService`)."""
        self._permissions.require(permissions.MANAGE_FILES)
        return self._store.delete(sha256)

    def offline_location(self, sha256: str):
        """(volume, status) if the content is recorded on a volume that can't be
        reached right now -- so a missing file can be told apart from one on a
        drive that isn't plugged in."""
        return self._store.offline_location(sha256)

    def local_path(self, sha256: str) -> Path | None:
        """Path of the object's bytes on local disk, for streaming it out
        without loading it into memory; None when files aren't on disk here
        (a bucket: use `stream` or `download_url`). FileNotFoundError when
        the content is on no drive here."""
        if self._volumes is None:
            return None
        return self._volumes.object_path(sha256)

    def stream(self, sha256: str) -> Iterator[bytes]:
        """The object's bytes a chunk at a time, wherever they are kept."""
        with self._store.open(sha256) as f:
            while chunk := f.read(_CHUNK):
                yield chunk

    def retrieve(self, sha256: str) -> bytes:
        """Return the object's bytes."""
        return self._store.get(sha256)

    def exists(self, sha256: str) -> bool:
        return self._store.exists(sha256)

    def size_of(self, sha256: str) -> int | None:
        return self._store.size_of(sha256)

    def object_path(self, sha256: str) -> Path:
        """The object's path on disk. Only for files on drives on this machine."""
        if self._volumes is None:
            raise FileNotFoundError(f"Object {sha256} is not on a drive here")
        return self._volumes.object_path(sha256)

    # -- straight to and from storage (`direct_files`) ------------------------

    def upload_target(self, sha256: str, size: int) -> DirectUpload | None:
        """Where an uploader may put the bytes itself, or None when they must
        be sent through civex (`store_stream`)."""
        self._permissions.require(permissions.MANAGE_FILES)
        return self._store.upload_target(sha256, size)

    def complete_upload(
        self,
        sha256: str,
        size: int,
        filename: str,
        upload_id: str | None = None,
        parts: list[UploadedPart] | None = None,
    ) -> FileRef:
        self._permissions.require(permissions.MANAGE_FILES)
        return self._store.complete_upload(sha256, size, filename, upload_id, parts)

    def download_url(self, sha256: str, filename: str | None = None) -> str | None:
        """Where the bytes can be fetched from directly, or None when civex
        must serve them."""
        return self._store.download_url(sha256, filename)
