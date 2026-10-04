from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from civex.config import Config, PlacementConfig, VolumeConfig, save_config
from civex.domain.dtos import (
    VOLUME_CONFIG_STATES,
    VOLUME_WRONG_DRIVE,
    DirectoryEntry,
    DirectoryListing,
    PathInspection,
    StorageLocation,
    VolumeStatus,
)
from civex.domain.placement import PLACEMENT_POLICIES, PLACEMENT_SPILL
from civex.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex import fs_locations

_UNSET = object()
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _prepare_path(path: str) -> str:
    """A volume path as it is stored: forward slashes, `~` expanded."""
    return os.path.expanduser(_normalize_path(path.strip()))


class StoreService:
    def __init__(self, config: Config, store: VolumeAwareFileObjectStore) -> None:
        self._config = config
        self._store = store

    def volume_stats(self) -> list[dict]:
        return self._store.volume_stats()

    def add_volume(
        self,
        name: str,
        path: str,
        allocated_gb: float | None = None,
        add_to_queue: bool = False,
    ) -> None:
        """Add a volume. `add_to_queue` also puts it in the general write
        queue; leave it out for a volume that only homes specific collections."""
        if not _NAME_RE.match(name):
            raise ValidationError(
                f"Volume name '{name}' is invalid. Use only letters, digits, hyphens, and underscores."
            )
        sc = self._config.store_config
        if name in sc.volumes:
            raise AlreadyExistsError(f"Volume '{name}' already exists")
        path = _prepare_path(path)
        inspection = self.inspect_path(path)
        if inspection.problems:
            raise ValidationError(" ".join(inspection.problems))
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
        if add_to_queue:
            sc.volume_queue.append(name)
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

    def set_volume_state(self, name: str, state: str) -> None:
        """Mark a volume active, read-only (readable, never written) or retired.

        Re-reads config.toml before writing it: this is also done by transfers
        that run for hours, and must never write back a stale copy over edits
        made in the meantime. The in-memory view is updated too, so it takes
        effect at once."""
        if state not in VOLUME_CONFIG_STATES:
            raise ValidationError(
                f"A volume's state must be one of: {', '.join(VOLUME_CONFIG_STATES)}"
            )
        sc = self._config.store_config
        if name not in sc.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        from civex.config import load_config

        fresh = load_config()
        if name not in fresh.store_config.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        fresh.store_config.volumes[name].state = state
        save_config(fresh)
        sc.volumes[name].state = state

    def restore_volume_state(self, name: str, before: str) -> None:
        """Put back the state a transfer changed, but only if it is still the one
        the transfer set (read-only), judged from config.toml as it is now, not
        from this process's copy: someone may have changed it since."""
        from civex.config import load_config

        fresh = load_config().store_config.volumes.get(name)
        if fresh is not None and fresh.state == "readonly":
            self.set_volume_state(name, before)

    def update_volume(
        self, name: str, *, path: str | None = None, allocated_gb=_UNSET
    ) -> None:
        sc = self._config.store_config
        if name not in sc.volumes:
            raise NotFoundError(f"Volume '{name}' not found")
        vc = sc.volumes[name]
        if path is not None:
            vc.path = _prepare_path(path)
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

    # -- choosing a folder: browsing and checking before adding ------------
    #
    # Everything here touches the filesystem through fs_locations.guarded, so a
    # network drive that has stopped answering is reported, not waited on.

    def browse_directory(
        self, path: str | None = None, *, show_hidden: bool = False
    ) -> DirectoryListing:
        """The folders inside `path` (the home folder when omitted), plus
        places to start from. Folders only: this is for picking a location,
        not for looking at files."""
        if path and fs_locations.looks_like_network_address(path):
            raise ValidationError(_NETWORK_ADDRESS_HELP)
        target = fs_locations.normalise(path or "~")
        try:
            raw, truncated = fs_locations.guarded(
                f"browse:{target}",
                fs_locations.list_subdirectories,
                target,
                show_hidden=show_hidden,
            )
        except FileNotFoundError:
            raise NotFoundError(f"Folder '{target}' not found") from None
        except NotADirectoryError:
            raise ValidationError(f"'{target}' is not a folder") from None
        except PermissionError:
            raise ValidationError(f"Permission denied: can't open '{target}'") from None
        except fs_locations.Unresponsive:
            raise ValidationError(_not_responding(target)) from None
        here = Path(target)
        # A root (`/`, `C:/`) has no parent; `Path` knows that on every OS.
        parent = None if here.parent == here else here.parent.as_posix()
        return DirectoryListing(
            path=target,
            parent=parent,
            entries=[DirectoryEntry(name=n, path=p) for n, p in raw],
            truncated=truncated,
            locations=self._locations(),
            hint=fs_locations.platform_hint(),
        )

    def create_folder(self, parent: str, name: str) -> str:
        """Create `name` inside `parent` and return its path."""
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValidationError("A folder name can't be empty or contain slashes.")
        folder = fs_locations.normalise(os.path.join(parent, name))
        try:
            fs_locations.guarded(f"mkdir:{folder}", os.mkdir, folder)
        except FileExistsError:
            raise AlreadyExistsError(f"'{folder}' already exists") from None
        except FileNotFoundError:
            raise NotFoundError(f"Folder '{parent}' not found") from None
        except PermissionError:
            raise ValidationError(
                f"Permission denied: can't create a folder in '{parent}'"
            ) from None
        except fs_locations.Unresponsive:
            raise ValidationError(_not_responding(parent)) from None
        return folder

    def _locations(self) -> list[StorageLocation]:
        """Places to start browsing from. Free space is read for local places
        only: asking a network drive can take as long as its timeout, and a
        list of places must come back at once. (`inspect_path` reads it for the
        one location actually chosen.)"""

        def at(
            label: str, path: str, kind: str, drive: fs_locations.Drive | None = None
        ):
            network = bool(drive and drive.network)
            free, total = (None, None) if network else fs_locations.disk_usage(path)
            return StorageLocation(
                label,
                path,
                kind,
                free,
                total,
                network=network,
                source=drive.source if drive else None,
            )

        places = [
            at("Project", fs_locations.normalise(str(self._store._root)), "project"),
            at("Home", fs_locations.normalise("~"), "home"),
        ]
        places += [
            at(d.label, d.path, "drive", d) for d in fs_locations.mounted_drives()
        ]
        return places

    def inspect_path(self, path: str) -> PathInspection:
        """Everything adding `path` as a volume would involve. The rules that
        block an add are decided here, and `add_volume` enforces the same
        ones, so what the form previews is what happens."""
        if fs_locations.looks_like_network_address(path):
            return self._blocked(path, _NETWORK_ADDRESS_HELP)
        sc = self._config.store_config
        # Resolved exactly as the store will resolve the configured path: a
        # relative path is under the project root, and whether the volume counts
        # as inside the project is the store's own rule.
        candidate = VolumeConfig(name="_candidate", path=_prepare_path(path))
        shown = fs_locations.normalise(str(self._store._resolve_path(candidate)))
        root = Path(shown)
        project = Path(fs_locations.normalise(str(self._store._root)))
        inside_project = self._store._inside_project(candidate)
        is_network = fs_locations.is_network_path(shown)
        try:
            facts = fs_locations.guarded(f"inspect:{shown}", _fs_facts, root, project)
        except fs_locations.Unresponsive:
            return self._blocked(shown, _not_responding(shown), is_network=is_network)

        existing = next(
            (
                n
                for n, v in sc.volumes.items()
                if fs_locations.normalise(str(self._store._resolve_path(v))) == shown
            ),
            None,
        )
        marker = facts.marker
        marker_volume = next(
            (n for n, v in sc.volumes.items() if marker and v.id == marker), None
        )

        problems: list[str] = []
        warnings: list[str] = []
        if facts.exists and not facts.is_dir:
            problems.append(f"'{shown}' is a file, not a folder.")
        if existing is not None:
            problems.append(f"That folder is already the volume '{existing}'.")
        elif marker_volume is not None:
            problems.append(
                f"This is the drive of volume '{marker_volume}'. Plug in a different "
                "drive, or use that volume."
            )
        if not facts.writable:
            problems.append(
                f"Civex can't write to '{facts.anchor}'."
                if facts.exists
                else f"Civex can't create this folder: '{facts.anchor}' isn't writable."
            )
        if not facts.exists:
            warnings.append(
                "This folder doesn't exist yet, so Civex will create it."
                + (
                    ""
                    if inside_project
                    else " If it should be on a removable or network drive, check the "
                    "drive is connected first: otherwise the folder is created on "
                    "this computer's own disk."
                )
            )
        if marker and marker_volume is None:
            warnings.append(
                "This folder carries the identity of a Civex volume from another "
                "project. That identity is kept."
            )
        if facts.has_data and not marker:
            warnings.append(
                "This folder already holds Civex files. They become available through "
                "this volume."
            )
        if is_network:
            warnings.append(
                "This is a network location. It can be slow, and its files become "
                "unavailable if the connection drops: Civex marks the volume offline "
                "while it isn't responding."
            )
        elif facts.same_disk and not inside_project:
            warnings.append(
                "This is on the same disk as the project, so it won't protect the "
                "files if that disk fails or is unplugged."
            )
        return PathInspection(
            path=shown,
            exists=facts.exists,
            is_dir=facts.is_dir,
            writable=facts.writable,
            will_create=not facts.exists,
            inside_project=inside_project,
            same_disk_as_project=facts.same_disk,
            free_bytes=facts.free,
            total_bytes=facts.total,
            existing_volume=existing,
            marker_volume=marker_volume,
            has_civex_data=facts.has_data,
            problems=problems,
            warnings=warnings,
            is_network=is_network,
        )

    @staticmethod
    def _blocked(
        path: str, problem: str, *, is_network: bool = False
    ) -> PathInspection:
        """An inspection that stops at one problem, for a location that can't
        be examined at all."""
        return PathInspection(
            path=path,
            exists=False,
            is_dir=False,
            writable=False,
            will_create=False,
            inside_project=False,
            same_disk_as_project=None,
            free_bytes=None,
            total_bytes=None,
            existing_volume=None,
            marker_volume=None,
            has_civex_data=False,
            problems=[problem],
            warnings=[],
            is_network=is_network,
        )


_NETWORK_ADDRESS_HELP = (
    "That looks like a network address. Civex uses network drives that are already "
    "mounted on this computer: mount it first (for example under /mnt on Linux, or "
    "map it to a drive letter on Windows), then choose the mounted folder."
)


def _not_responding(path: str) -> str:
    return (
        f"'{path}' isn't responding. If it is a network drive, check the "
        "connection and try again."
    )


@dataclass
class _FsFacts:
    exists: bool
    is_dir: bool
    writable: bool
    anchor: Path
    free: int | None
    total: int | None
    same_disk: bool | None
    marker: str | None
    has_data: bool


def _fs_facts(root: Path, project: Path) -> _FsFacts:
    """Everything `inspect_path` needs to read from the disk, gathered in one
    call so it can be run under a single time limit."""
    from civex.repositories.local.file_store import _read_marker

    exists = root.exists()
    is_dir = root.is_dir()
    anchor = fs_locations.nearest_existing(str(root))
    free, total = fs_locations.disk_usage(str(root))
    try:
        same_disk: bool | None = os.stat(anchor).st_dev == os.stat(project).st_dev
    except OSError:
        same_disk = None
    has_data = False
    if is_dir:
        try:
            has_data = (root / "manifest.jsonl").is_file() or any(
                len(p.name) == 2 and p.is_dir() for p in root.iterdir()
            )
        except OSError:
            has_data = False
    return _FsFacts(
        exists=exists,
        is_dir=is_dir,
        writable=os.access(anchor, os.W_OK | os.X_OK),
        anchor=anchor,
        free=free,
        total=total,
        same_disk=same_disk,
        marker=_read_marker(root) if is_dir else None,
        has_data=has_data,
    )
