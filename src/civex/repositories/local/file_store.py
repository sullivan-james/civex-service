"""
Content-addressed local file store.

Files are stored at:
    <objects_dir>/<sha256[:2]>/<sha256[2:]>

This mirrors git's object store layout — the two-character prefix keeps any
single directory from growing unbounded.

Files are immutable once written. put() is idempotent.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from civex.domain.dtos import FileRef


class LocalFileObjectStore:
    def __init__(self, objects_dir: Path) -> None:
        self._root = objects_dir

    def put(self, data: bytes, original_filename: str) -> FileRef:
        sha256 = hashlib.sha256(data).hexdigest()
        dest = self._object_path(sha256)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return FileRef(sha256=sha256, filename=original_filename, size=len(data))

    def get(self, sha256: str) -> bytes:
        return self._object_path(sha256).read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._object_path(sha256).exists()

    def object_path(self, sha256: str) -> Path:
        return self._object_path(sha256)

    def _object_path(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256[2:]
