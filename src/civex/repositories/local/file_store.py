"""
Volume-aware content-addressed file store.

Files are stored at:
    <volume_path>/<sha256[:2]>/<sha256[2:]>

On write, the store walks the configured queue and picks the first volume that
passes both gates:
  1. Civex allocation: civex_used + incoming_size <= allocated_gb
  2. Physical disk headroom: disk_free > full_below_gb

Each volume also gets a <volume_path>/manifest.jsonl -- one JSON line per
object recording {sha256, filename, size} the first time it's written. Object
paths carry no filename or extension of their own, so this is what makes a
copy of the volume directory self-describing without the database: someone
with only the raw files (no civex install, no DB) can still tell what each
blob originally was.

On read, volumes are searched in definition order. The `volume` field in
FileRef is a fast hint but resolution always falls back to scanning.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import AsyncIterable

from civex.config import StoreConfig, VolumeConfig
from civex.domain.dtos import FileRef, StoredObjectInfo
from civex.domain.exceptions import AllVolumesFull, VolumeUnavailableError

_SCRATCH_DIRNAME = ".tmp"


class VolumeAwareFileObjectStore:
    def __init__(self, store_config: StoreConfig, project_root: Path) -> None:
        self._cfg = store_config
        self._root = project_root
        self._used_cache: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def put(self, data: bytes, original_filename: str) -> FileRef:
        sha256 = hashlib.sha256(data).hexdigest()
        size = len(data)

        # If already stored in any volume, return immediately (idempotent).
        existing = self._find_object(sha256)
        if existing is not None:
            vol_name = self._volume_of(sha256) or self._cfg.volume_queue[0]
            return FileRef(
                sha256=sha256, filename=original_filename, size=size, volume=vol_name
            )

        reasons: list[str] = []
        for vol_name in self._cfg.volume_queue:
            can, reason = self._can_write(vol_name, size)
            if not can:
                reasons.append(f"{vol_name}: {reason}")
                continue
            dest = self._object_path(sha256, vol_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(data)
                self._used_cache.pop(vol_name, None)
                self._append_manifest(vol_name, sha256, original_filename, size)
                return FileRef(
                    sha256=sha256,
                    filename=original_filename,
                    size=size,
                    volume=vol_name,
                )
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    reasons.append(f"{vol_name}: no space left on device")
                    continue
                raise VolumeUnavailableError(
                    f"Cannot write to volume '{vol_name}': {e}"
                ) from e

        raise AllVolumesFull(
            f"No volume in queue has space for {size / 1_048_576:.1f} MB. "
            + "; ".join(reasons)
        )

    async def put_stream(
        self,
        chunks: AsyncIterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
    ) -> FileRef:
        """Stream-write `chunks` straight to disk, hashing incrementally so
        the full content never has to fit in memory at once -- unlike put(),
        which needs the whole object in a single `bytes` up front. Chunks
        are written to a scratch file on the chosen volume and the file is
        renamed into its content-addressed path once the digest is known;
        same-filesystem rename is atomic, so a reader can never observe a
        partially-written object at its final path.

        Unlike put(), volume selection can't fall back mid-stream: once
        bytes have been consumed from `chunks` (typically a live HTTP
        request body), they can't be replayed against a different volume.
        `size_hint` (e.g. a Content-Length header), when known upfront,
        still lets the allocation/headroom gate reject an unsuitable volume
        before a single byte is written; without it, running out of space
        partway through fails the upload outright instead of retrying on
        the next volume in queue.
        """
        reasons: list[str] = []
        for vol_name in self._cfg.volume_queue:
            can, reason = self._can_write(vol_name, size_hint or 0)
            if not can:
                reasons.append(f"{vol_name}: {reason}")
                continue

            vc = self._cfg.volumes[vol_name]
            scratch_dir = self._resolve_path(vc) / _SCRATCH_DIRNAME
            scratch_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = scratch_dir / f"{uuid.uuid4().hex}.part"

            hasher = hashlib.sha256()
            size = 0
            try:
                with tmp_path.open("wb") as f:
                    async for chunk in chunks:
                        if not chunk:
                            continue
                        hasher.update(chunk)
                        f.write(chunk)
                        size += len(chunk)
            except OSError as e:
                tmp_path.unlink(missing_ok=True)
                if e.errno == errno.ENOSPC:
                    raise VolumeUnavailableError(
                        f"Volume '{vol_name}' ran out of space mid-upload "
                        f"({size / 1_048_576:.1f} MB written); the upload "
                        "can't resume on another volume once bytes have "
                        "been streamed -- retry the upload from the start."
                    ) from e
                raise VolumeUnavailableError(
                    f"Cannot write to volume '{vol_name}': {e}"
                ) from e

            sha256 = hasher.hexdigest()

            existing = self._find_object(sha256)
            if existing is not None:
                tmp_path.unlink(missing_ok=True)
                vol_of_existing = self._volume_of(sha256) or vol_name
                return FileRef(
                    sha256=sha256,
                    filename=original_filename,
                    size=size,
                    volume=vol_of_existing,
                )

            dest = self._object_path(sha256, vol_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, dest)
            self._used_cache.pop(vol_name, None)
            self._append_manifest(vol_name, sha256, original_filename, size)
            return FileRef(
                sha256=sha256, filename=original_filename, size=size, volume=vol_name
            )

        raise AllVolumesFull(
            "No volume in queue has space"
            + (f" for {size_hint / 1_048_576:.1f} MB" if size_hint else "")
            + ". "
            + "; ".join(reasons)
        )

    def get(self, sha256: str) -> bytes:
        path = self._find_object(sha256)
        if path is None:
            raise FileNotFoundError(f"Object {sha256} not found in any volume")
        return path.read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._find_object(sha256) is not None

    def object_path(self, sha256: str) -> Path:
        path = self._find_object(sha256)
        if path is None:
            raise FileNotFoundError(f"Object {sha256} not found in any volume")
        return path

    def list_objects(self) -> list[StoredObjectInfo]:
        """Every object actually on disk, across every configured volume --
        including volumes no longer in the write queue. Walks the volume
        directories rather than trusting manifest.jsonl: the manifest is
        append-only and best-effort (a crash between write and append would
        leave it short), so it's fine for display metadata but not as the
        authoritative existence check GC sweeps against.
        """
        results = []
        for name, vc in self._cfg.volumes.items():
            root = self._resolve_path(vc)
            if not root.exists():
                continue
            for f in root.rglob("*"):
                if not f.is_file() or f.name == "manifest.jsonl":
                    continue
                if _SCRATCH_DIRNAME in f.relative_to(root).parts:
                    continue  # in-progress put_stream() upload, not a real object
                sha256 = f.parent.name + f.name
                stat = f.stat()
                results.append(
                    StoredObjectInfo(
                        sha256=sha256,
                        volume=name,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    )
                )
        return results

    def sweep_stale_scratch(
        self, older_than_seconds: float, dry_run: bool = False
    ) -> int:
        """Count (and, unless dry_run, remove) put_stream() scratch files
        (`.tmp/*.part`) older than `older_than_seconds` -- left behind when
        an upload was interrupted (client disconnect, process kill) before
        the rename into place. These are invisible to list_objects(), so
        nothing else cleans them up. Age is judged conservatively: an
        in-progress upload keeps writing to its part file, which bumps its
        mtime, so anything past the threshold is one that stopped
        receiving bytes, not just a slow one."""
        cutoff = time.time() - older_than_seconds
        count = 0
        for vc in self._cfg.volumes.values():
            scratch_dir = self._resolve_path(vc) / _SCRATCH_DIRNAME
            if not scratch_dir.exists():
                continue
            for f in scratch_dir.glob("*.part"):
                try:
                    if f.stat().st_mtime < cutoff:
                        count += 1
                        if not dry_run:
                            f.unlink()
                except OSError:
                    continue
        return count

    def delete(self, sha256: str, volume: str | None = None) -> bool:
        """Remove a stored object. `volume` is an optional hint (e.g. from
        list_objects) to skip the full-volume scan; falls back to searching
        every volume if the hint misses. Returns False if not found."""
        path = None
        if volume is not None:
            vc = self._cfg.volumes.get(volume)
            if vc is not None:
                candidate = self._resolve_path(vc) / sha256[:2] / sha256[2:]
                if candidate.exists():
                    path = candidate
        if path is None:
            volume = self._volume_of(sha256)
            path = self._find_object(sha256)
        if path is None:
            return False
        path.unlink()
        if volume is not None:
            self._used_cache.pop(volume, None)
        return True

    # ------------------------------------------------------------------
    # Stats (for CLI / UI)
    # ------------------------------------------------------------------

    def _stat_volume(
        self, name: str, vc: VolumeConfig, warn_pct: float, *, in_queue: bool
    ) -> dict:
        path = self._resolve_path(vc)
        available = path.exists()
        disk_free = disk_total = None
        if available:
            try:
                du = shutil.disk_usage(path)
                disk_free = du.free
                disk_total = du.total
            except OSError:
                available = False

        civex_used = self._civex_used(name) if available else None
        allocated_bytes = (
            int(vc.allocated_gb * 1024**3) if vc.allocated_gb is not None else None
        )

        warning = False
        if available:
            if allocated_bytes and civex_used is not None and allocated_bytes > 0:
                if (allocated_bytes - civex_used) / allocated_bytes < warn_pct:
                    warning = True
            if disk_free is not None and disk_total and disk_total > 0:
                if disk_free / disk_total < warn_pct:
                    warning = True

        return {
            "name": name,
            "path": vc.path,
            "allocated_gb": vc.allocated_gb,
            "civex_used_bytes": civex_used,
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total,
            "available": available,
            "warning": warning,
            "in_queue": in_queue,
        }

    def volume_stats(self) -> list[dict]:
        warn_pct = self._cfg.warn_below_pct / 100.0
        results = []
        for name in self._cfg.volume_queue:
            vc = self._cfg.volumes.get(name)
            if vc is None:
                continue
            results.append(self._stat_volume(name, vc, warn_pct, in_queue=True))
        # Include volumes defined but not in queue
        for name, vc in self._cfg.volumes.items():
            if name not in self._cfg.volume_queue:
                results.append(self._stat_volume(name, vc, warn_pct, in_queue=False))
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_path(self, vc: VolumeConfig) -> Path:
        p = Path(vc.path)
        return p if p.is_absolute() else self._root / p

    def _object_path(self, sha256: str, volume: str) -> Path:
        vc = self._cfg.volumes[volume]
        return self._resolve_path(vc) / sha256[:2] / sha256[2:]

    def _append_manifest(
        self, volume: str, sha256: str, filename: str, size: int
    ) -> None:
        """Append one JSONL line recording this object's original filename.

        Only called on first write of a given hash (the idempotent-existing
        path in put() returns before reaching this), so each hash gets one
        line -- or, if two different uploads race to store the same content
        under different names, one line per name, which is useful rather
        than a bug.
        """
        vc = self._cfg.volumes[volume]
        manifest_path = self._resolve_path(vc) / "manifest.jsonl"
        line = json.dumps(
            {"sha256": sha256, "filename": filename, "size": size},
            ensure_ascii=False,
        )
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _find_object(self, sha256: str) -> Path | None:
        for vc in self._cfg.volumes.values():
            p = self._resolve_path(vc) / sha256[:2] / sha256[2:]
            if p.exists():
                return p
        return None

    def _volume_of(self, sha256: str) -> str | None:
        for name, vc in self._cfg.volumes.items():
            p = self._resolve_path(vc) / sha256[:2] / sha256[2:]
            if p.exists():
                return name
        return None

    def _civex_used(self, volume: str) -> int:
        if volume in self._used_cache:
            return self._used_cache[volume]
        vc = self._cfg.volumes.get(volume)
        if vc is None:
            return 0
        root = self._resolve_path(vc)
        if not root.exists():
            self._used_cache[volume] = 0
            return 0
        total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        self._used_cache[volume] = total
        return total

    def _can_write(self, volume: str, incoming_size: int) -> tuple[bool, str]:
        vc = self._cfg.volumes.get(volume)
        if vc is None:
            return False, "volume not configured"

        path = self._resolve_path(vc)
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return False, f"path unavailable: {e}"

        if vc.allocated_gb is not None:
            allocated = int(vc.allocated_gb * 1024**3)
            used = self._civex_used(volume)
            if used + incoming_size > allocated:
                remaining = max(0, allocated - used)
                return False, (
                    f"allocation limit reached "
                    f"({remaining / 1_048_576:.0f} MB of {vc.allocated_gb:.1f} GB remaining)"
                )

        try:
            disk = shutil.disk_usage(path)
        except OSError as e:
            return False, f"cannot check disk space: {e}"
        full_bytes = int(self._cfg.full_below_gb * 1024**3)
        if disk.free < full_bytes + incoming_size:
            return False, (
                f"disk too full ({disk.free / 1_048_576:.0f} MB free, "
                f"need {self._cfg.full_below_gb:.1f} GB headroom)"
            )

        return True, ""


# Backward-compat alias so existing imports don't break immediately.
LocalFileObjectStore = VolumeAwareFileObjectStore
