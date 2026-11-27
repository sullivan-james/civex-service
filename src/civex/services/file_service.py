from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import AsyncIterable

from civex.domain import permissions
from civex.domain.dtos import DirectUpload, FileRef, UploadedPart
from civex.domain.exceptions import NotFoundError
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
        # Whether content may be given to this caller (set by `context.py`
        # for one who cannot read every collection; always, for one who can).
        self.readable: Callable[[str], bool] = lambda sha256: True

    # `collection_id` (here and below) is the id of the collection the file is
    # for. It only steers where new content is written -- see
    # VolumeAwareFileObjectStore._write_candidates -- and never causes content
    # that already exists to be stored again.

    def check_readable(self, sha256: str) -> None:
        """404 for content that only collections the caller cannot read use,
        so a file is no more reachable by its hash than its record is."""
        if not self.readable(sha256):
            raise NotFoundError("File not found")

    def _may_add(self, collection_id: str | None) -> None:
        """Adding a file is `ADD_FILES` in the collection it is for (the
        caller must see it: a hidden collection is not there to add to), or in
        some collection when it is not for one."""
        if collection_id is None:
            self._permissions.require_somewhere(permissions.ADD_FILES)
            return
        if not self._permissions.read_scope().sees(collection_id):
            raise NotFoundError("Collection not found")
        self._permissions.require(permissions.ADD_FILES, collection_id)

    def store(
        self,
        path: Path,
        collection_id: str | None = None,
        filename: str | None = None,
    ) -> FileRef:
        """Copy a file from disk into the object store in fixed-size chunks
        (never reading the whole file into memory). `filename` is the name it
        is stored under (default: the file's own)."""
        self._may_add(collection_id)
        return self._store.put_path(
            path, original_filename=filename, collection_id=collection_id
        )

    def store_unless_stored(
        self,
        path: Path,
        collection_id: str | None = None,
        filename: str | None = None,
    ) -> tuple[FileRef, bool]:
        """`store`, except that a file whose content is already stored is not
        copied again: its content hash is worked out first (the file is read
        once, never held whole) and, when the store has it, only the reference
        is made. Returns the reference and whether anything was stored."""
        self._may_add(collection_id)
        name = filename or path.name
        hasher = hashlib.sha256()
        with path.open("rb") as src:
            while chunk := src.read(_CHUNK):
                hasher.update(chunk)
        sha256 = hasher.hexdigest()
        if self._store.exists(sha256):
            volume = self._store.locate_volumes([sha256]).get(sha256)
            if volume is not None:
                size = self._store.size_of(sha256)
                if size is None:
                    size = path.stat().st_size
                return FileRef(sha256, name, size, volume), False
        ref = self._store.put_path(
            path, original_filename=name, collection_id=collection_id
        )
        return ref, True

    def store_bytes(
        self, data: bytes, filename: str, collection_id: str | None = None
    ) -> FileRef:
        """Store raw bytes (e.g. from an HTTP upload) in the object store."""
        self._may_add(collection_id)
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
        self._may_add(collection_id)
        return await self._store.put_stream(chunks, filename, size_hint, collection_id)

    def discard(self, sha256: str) -> bool:
        """Remove content just stored that turned out not to be wanted: a file
        taken in for a record save that was then refused. Every reachable copy
        goes (there is one, the one just written). The caller must know the
        content was new, since this doesn't ask what else uses it; anything
        it misses is left to the clean-up (`GCService`)."""
        self._permissions.require_somewhere(permissions.ADD_FILES)
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

    def exists_many(self, shas: Iterable[str]) -> set[str]:
        """Which of these are held, asked together."""
        return self._store.exists_many(shas)

    def size_of(self, sha256: str) -> int | None:
        return self._store.size_of(sha256)

    def sizes_of(self, shas: Iterable[str]) -> dict[str, int]:
        """The size of each of these that is held, the inventory asked once
        for all (a file it doesn't know is looked for one at a time)."""
        wanted = list(dict.fromkeys(shas))
        out = {
            sha: rows[0][1] for sha, rows in self._store.copies(wanted).items() if rows
        }
        for sha in wanted:
            if sha not in out and (size := self._store.size_of(sha)) is not None:
                out[sha] = size
        return out

    def object_path(self, sha256: str) -> Path:
        """The object's path on disk. Only for files on drives on this machine."""
        if self._volumes is None:
            raise FileNotFoundError(f"Object {sha256} is not on a drive here")
        return self._volumes.object_path(sha256)

    @contextlib.contextmanager
    def batched(self) -> Iterator[None]:
        """Many files stored in this block are recorded together (where the
        store can: `flush` before committing)."""
        batch = getattr(self._store, "batched_registration", None)
        if batch is None:
            yield
        else:
            with batch():
                yield

    def flush(self) -> None:
        flush = getattr(self._store, "flush_registrations", None)
        if flush is not None:
            flush()

    # -- a big file in parts (`file_parts`) -----------------------------------

    @property
    def takes_parts(self) -> bool:
        return bool(getattr(self._store, "supports_parts", False))

    def begin_parts(
        self, sha256: str, size: int, part_size: int
    ) -> tuple[int, list[int]]:
        self._may_add(None)
        return self._store.begin_parts(sha256, size, part_size)

    async def put_part(
        self, sha256: str, number: int, chunks: AsyncIterable[bytes]
    ) -> None:
        self._may_add(None)
        await self._store.put_part(sha256, number, chunks)

    def finish_parts(self, sha256: str, size: int, filename: str) -> FileRef:
        self._may_add(None)
        return self._store.finish_parts(sha256, size, filename)

    # -- straight to and from storage (`direct_files`) ------------------------

    def upload_target(self, sha256: str, size: int) -> DirectUpload | None:
        """Where an uploader may put the bytes itself, or None when they must
        be sent through civex (`store_stream`)."""
        self._permissions.require_somewhere(permissions.ADD_FILES)
        return self._store.upload_target(sha256, size)

    def complete_upload(
        self,
        sha256: str,
        size: int,
        filename: str,
        upload_id: str | None = None,
        parts: list[UploadedPart] | None = None,
    ) -> FileRef:
        self._permissions.require_somewhere(permissions.ADD_FILES)
        return self._store.complete_upload(sha256, size, filename, upload_id, parts)

    def download_url(self, sha256: str, filename: str | None = None) -> str | None:
        """Where the bytes can be fetched from directly, or None when civex
        must serve them."""
        return self._store.download_url(sha256, filename)
