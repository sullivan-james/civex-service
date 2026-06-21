from __future__ import annotations

import re

from civex.config import Config, VolumeConfig, save_config
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError, VolumeUnavailableError
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

    def add_volume(self, name: str, path: str, allocated_gb: float | None = None) -> None:
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
            raise VolumeUnavailableError(f"Cannot access volume path '{resolved}': {e}") from e
        sc.volumes[name] = vc
        save_config(self._config)

    def update_volume(self, name: str, *, path: str | None = None, allocated_gb=_UNSET) -> None:
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
        if not force:
            used = self._store._civex_used(name)
            if used > 0:
                count = sum(1 for _ in self._store._resolve_path(sc.volumes[name]).rglob("*") if _.is_file())
                raise ValidationError(
                    f"Volume '{name}' contains {count} object(s) ({used / 1_048_576:.1f} MB). "
                    "Move or delete them before removing the volume, or use force=true to remove anyway "
                    "(existing file references will become unresolvable)."
                )
        sc.volume_queue = [n for n in sc.volume_queue if n != name]
        del sc.volumes[name]
        save_config(self._config)

    def set_queue(self, names: list[str]) -> None:
        sc = self._config.store_config
        for n in names:
            if n not in sc.volumes:
                raise NotFoundError(f"Volume '{n}' not found")
        sc.volume_queue = list(names)
        save_config(self._config)
