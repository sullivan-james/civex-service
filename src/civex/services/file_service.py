from __future__ import annotations

from pathlib import Path

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
        """Read a file from disk and store it in the object store."""
        return self._store.put(path.read_bytes(), path.name)

    def store_bytes(self, data: bytes, filename: str) -> FileRef:
        """Store raw bytes (e.g. from an HTTP upload) in the object store."""
        return self._store.put(data, filename)

    def retrieve(self, sha256: str) -> bytes:
        """Return object bytes, fetching from the remote and caching locally if needed."""
        if self._store.exists(sha256):
            return self._store.get(sha256)
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
