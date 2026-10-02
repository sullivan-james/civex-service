from __future__ import annotations

import re
import uuid

from civex.config import Config, PlacementConfig, VolumeConfig, save_config
from civex.domain.dtos import VOLUME_WRONG_DRIVE, VolumeStatus
from civex.domain.placement import PLACEMENT_POLICIES, PLACEMENT_SPILL
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.repositories.local.file_store import VolumeAwareFileObjectStore

_UNSET = object()
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


class StoreService:
    def __init__(self, config: Config, store: VolumeAwareFileObjectStore) -> None:
        self._config = config
        self._store = store

    def volume_stats(self) -> list[dict]:
        return self._store.volume_stats()

    def add_volume(
        self, name: str, path: str, allocated_gb: float | None = None
    ) -> None:
        if not _NAME_RE.match(name):
            raise ValidationError(
                f"Volume name '{name}' is invalid. Use only letters, digits, hyphens, and underscores."
            )
        sc = self._config.store_config
        if name in sc.volumes:
            raise AlreadyExistsError(f"Volume '{name}' already exists")
        path = _normalize_path(path)
        vc = VolumeConfig(name=name, path=path, allocated_gb=allocated_gb)
        resolved = self._store._resolve_path(vc)
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise VolumeUnavailableError(
                f"Cannot access volume path '{resolved}': {e}"
            ) from e
        sc.volumes[name] = vc
        try:
            status = self._store.register_volume(name)
            if status.state == VOLUME_WRONG_DRIVE:
                raise ValidationError(f"{status.reason}. {status.fix}")
        except Exception:
            del sc.volumes[name]
            raise
        save_config(self._config)

    def adopt_volume(self, name: str) -> VolumeStatus:
        """Declare that the drive at the volume's path is that volume: rewrite
        its identity marker. For a volume reported as the wrong drive when it
        is in fact the right one (marker lost, drive re-formatted)."""
        if name not in self._config.store_config.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        status = self._store.adopt_volume(name)
        save_config(self._config)
        return status

    def update_volume(
        self, name: str, *, path: str | None = None, allocated_gb=_UNSET
    ) -> None:
        sc = self._config.store_config
        if name not in sc.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        vc = sc.volumes[name]
        if path is not None:
            vc.path = _normalize_path(path)
        if allocated_gb is not _UNSET:
            vc.allocated_gb = allocated_gb
        self._store._used_cache.pop(name, None)
        save_config(self._config)

    def remove_volume(self, name: str, force: bool = False) -> None:
        sc = self._config.store_config
        if name not in sc.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        homed = [cid for cid, place in sc.placement.items() if place.volume == name]
        if homed and not force:
            raise ValidationError(
                f"{len(homed)} collection(s) are homed on volume '{name}'. Clear "
                "their placement first, or use force to clear it for them."
            )
        if not force:
            used = self._store._civex_used(name)
            if used > 0:
                count = sum(
                    1
                    for _ in self._store._resolve_path(sc.volumes[name]).rglob("*")
                    if _.is_file()
                )
                raise ValidationError(
                    f"Volume '{name}' contains {count} object(s) ({used / 1_048_576:.1f} MB). "
                    "Move or delete them before removing the volume, or use force=true to remove anyway "
                    "(existing file references will become unresolvable)."
                )
        sc.volume_queue = [n for n in sc.volume_queue if n != name]
        for cid in homed:
            del sc.placement[cid]
        del sc.volumes[name]
        save_config(self._config)

    def set_queue(self, names: list[str]) -> None:
        sc = self._config.store_config
        for n in names:
            if n not in sc.volumes:
                raise NotFoundError(f"Volume '{n}' not found")
        sc.volume_queue = list(names)
        save_config(self._config)

    # -- placement: which volume a collection's new files go to ------------
    #
    # Held in config.toml keyed by collection *id*, so renaming a collection
    # changes nothing here. A placement only steers where content that isn't
    # stored yet is written; existing content is reused wherever it lives.

    def placements(self) -> dict[str, PlacementConfig]:
        return dict(self._config.store_config.placement)

    def set_placement(
        self,
        collection_id: str,
        volume: str,
        on_unavailable: str = PLACEMENT_SPILL,
    ) -> PlacementConfig:
        try:
            collection_id = str(uuid.UUID(collection_id))
        except ValueError:
            raise ValidationError(f"'{collection_id}' is not a collection id") from None
        sc = self._config.store_config
        if volume not in sc.volumes:
            raise NotFoundError(f"Volume '{volume}' not found")
        if on_unavailable not in PLACEMENT_POLICIES:
            raise ValidationError(
                f"on_unavailable must be one of: {', '.join(PLACEMENT_POLICIES)}"
            )
        place = PlacementConfig(volume=volume, on_unavailable=on_unavailable)
        sc.placement[collection_id] = place
        save_config(self._config)
        return place

    def clear_placement(self, collection_id: str) -> bool:
        """Remove a collection's placement. True if it had one."""
        sc = self._config.store_config
        if collection_id not in sc.placement:
            return False
        del sc.placement[collection_id]
        save_config(self._config)
        return True
