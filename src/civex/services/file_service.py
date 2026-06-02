from __future__ import annotations

from pathlib import Path

from civex.domain.dtos import FileRef
from civex.repositories.protocols import FileObjectStore


class FileService:
    def __init__(self, store: FileObjectStore) -> None:
        self._store = store

    def store(self, path: Path) -> FileRef:
        """Read a file from disk and store it in the object store."""
        return self._store.put(path.read_bytes(), path.name)

    def retrieve(self, sha256: str) -> bytes:
        return self._store.get(sha256)

    def exists(self, sha256: str) -> bool:
        return self._store.exists(sha256)

    def object_path(self, sha256: str) -> Path:
        return self._store.object_path(sha256)
