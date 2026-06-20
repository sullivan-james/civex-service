"""
Volume-aware content-addressed file store.

Files are stored at:
    <volume_path>/<sha256[:2]>/<sha256[2:]>

On write, the store walks the configured queue and picks the first volume that
passes both gates:
  1. Civex allocation: civex_used + incoming_size <= allocated_gb
  2. Physical disk headroom: disk_free > full_below_gb

On read, volumes are searched in definition order. The `volume` field in
FileRef is a fast hint but resolution always falls back to scanning.
"""
from __future__ import annotations

import errno
import hashlib
import shutil
from pathlib import Path

from civex.config import StoreConfig, VolumeConfig
from civex.domain.dtos import FileRef
from civex.domain.exceptions import AllVolumesFull, VolumeUnavailableError


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
            return FileRef(sha256=sha256, filename=original_filename, size=size, volume=vol_name)

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
                return FileRef(sha256=sha256, filename=original_filename, size=size, volume=vol_name)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    reasons.append(f"{vol_name}: no space left on device")
                    continue
                raise VolumeUnavailableError(f"Cannot write to volume '{vol_name}': {e}") from e

        raise AllVolumesFull(
            f"No volume in queue has space for {size / 1_048_576:.1f} MB. "
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

    # ------------------------------------------------------------------
    # Stats (for CLI / UI)
    # ------------------------------------------------------------------

    def _stat_volume(self, name: str, vc: VolumeConfig, warn_pct: float, *, in_queue: bool) -> dict:
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
        allocated_bytes = int(vc.allocated_gb * 1024 ** 3) if vc.allocated_gb is not None else None

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
            allocated = int(vc.allocated_gb * 1024 ** 3)
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
        full_bytes = int(self._cfg.full_below_gb * 1024 ** 3)
        if disk.free < full_bytes + incoming_size:
            return False, (
                f"disk too full ({disk.free / 1_048_576:.0f} MB free, "
                f"need {self._cfg.full_below_gb:.1f} GB headroom)"
            )

        return True, ""


# Backward-compat alias so existing imports don't break immediately.
LocalFileObjectStore = VolumeAwareFileObjectStore
