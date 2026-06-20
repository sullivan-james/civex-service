"""
Project config — finds the nearest .civex/ directory (like git walks up from cwd)
and loads config.toml from it.

Minimal config.toml (local only):
    [db]
    url = "sqlite:///..."

With a remote (added by `civex remote set <url>`):
    [remote]
    url = "ssh://user@host:/srv/repos/myrepo"
    last_pushed_seq = 42   # optional, monotonic commit sequence number
    last_pulled_seq = 38   # optional
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from civex.domain.exceptions import ConfigError


@dataclass
class DBConfig:
    url: str


@dataclass
class RemoteConfig:
    url: str
    last_pushed_seq: int = 0
    last_pulled_seq: int = 0
    remote_civex: str = "civex"   # path to civex on the remote (for SSH transport)
    last_pushed_at: datetime | None = None
    last_pulled_at: datetime | None = None


@dataclass
class VolumeConfig:
    name: str
    path: str              # raw string — may be relative (resolved against project root) or absolute
    allocated_gb: float | None = None  # None = unlimited


@dataclass
class StoreConfig:
    volumes: dict[str, VolumeConfig]
    volume_queue: list[str]
    warn_below_pct: float = 10.0  # show warning in UI when less than this % of space remains
    full_below_gb: float = 1.0    # treat volume as full below this disk headroom (absolute)


def _default_store(project_root: Path) -> StoreConfig:
    default_vol = VolumeConfig(name="default", path=".civex/objects")
    return StoreConfig(volumes={"default": default_vol}, volume_queue=["default"])


@dataclass
class Config:
    project_root: Path
    db: DBConfig
    remote: RemoteConfig | None   # None when [remote] is absent — local-only mode
    store: StoreConfig | None = None  # None until first access; use store_config property

    @property
    def civex_dir(self) -> Path:
        return self.project_root / ".civex"

    @property
    def objects_dir(self) -> Path:
        return self.civex_dir / "objects"

    @property
    def store_config(self) -> StoreConfig:
        if self.store is None:
            self.store = _default_store(self.project_root)
        return self.store


def find_project_root() -> Path | None:
    """Walk up from cwd looking for a .civex directory."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        if (directory / ".civex").is_dir():
            return directory
    return None


def load_config() -> Config:
    root = find_project_root()
    if root is None:
        raise ConfigError("No civex project found. Run `civex init` to create one.")

    config_path = root / ".civex" / "config.toml"
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"Malformed config file ({config_path}): {e}. "
            "If the database URL contains backslashes (Windows path), replace them with forward slashes."
        )

    remote: RemoteConfig | None = None
    if "remote" in data:
        def _parse_dt(val: str | None) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)
            except ValueError:
                return None

        remote = RemoteConfig(
            url=data["remote"]["url"],
            last_pushed_seq=int(data["remote"].get("last_pushed_seq", 0)),
            last_pulled_seq=int(data["remote"].get("last_pulled_seq", 0)),
            remote_civex=data["remote"].get("remote_civex", "civex"),
            last_pushed_at=_parse_dt(data["remote"].get("last_pushed_at")),
            last_pulled_at=_parse_dt(data["remote"].get("last_pulled_at")),
        )

    store: StoreConfig | None = None
    if "store" in data:
        sd = data["store"]
        raw_vols = sd.get("volumes", {})
        volumes = {
            name: VolumeConfig(
                name=name,
                path=vcfg["path"],
                allocated_gb=vcfg.get("allocated_gb"),
            )
            for name, vcfg in raw_vols.items()
        }
        if not volumes:
            volumes = {"default": VolumeConfig(name="default", path=".civex/objects")}
        queue = sd.get("volume_queue", list(volumes.keys()))
        store = StoreConfig(
            volumes=volumes,
            volume_queue=queue,
            warn_below_pct=float(sd.get("warn_below_pct", 10.0)),
            full_below_gb=float(sd.get("full_below_gb", 1.0)),
        )

    return Config(
        project_root=root,
        db=DBConfig(url=data["db"]["url"]),
        remote=remote,
        store=store,
    )


def save_config(config: Config) -> None:
    """Write config back to .civex/config.toml."""
    lines: list[str] = [
        "[db]\n",
        f'url = "{config.db.url}"\n',
    ]
    if config.remote:
        lines += ["\n[remote]\n", f'url = "{config.remote.url}"\n']
        if config.remote.remote_civex != "civex":
            lines.append(f'remote_civex = "{config.remote.remote_civex}"\n')
        lines.append(f'last_pushed_seq = {config.remote.last_pushed_seq}\n')
        lines.append(f'last_pulled_seq = {config.remote.last_pulled_seq}\n')
        if config.remote.last_pushed_at:
            lines.append(f'last_pushed_at = "{config.remote.last_pushed_at.isoformat()}"\n')
        if config.remote.last_pulled_at:
            lines.append(f'last_pulled_at = "{config.remote.last_pulled_at.isoformat()}"\n')

    sc = config.store
    if sc is not None:
        is_default = (
            list(sc.volumes.keys()) == ["default"]
            and sc.volumes["default"].path == ".civex/objects"
            and sc.volumes["default"].allocated_gb is None
            and sc.volume_queue == ["default"]
            and sc.warn_below_pct == 10.0
            and sc.full_below_gb == 1.0
        )
        if not is_default:
            queue_str = ", ".join(f'"{n}"' for n in sc.volume_queue)
            lines += [
                "\n[store]\n",
                f'volume_queue = [{queue_str}]\n',
                f'warn_below_pct = {sc.warn_below_pct}\n',
                f'full_below_gb = {sc.full_below_gb}\n',
            ]
            for vol in sc.volumes.values():
                lines.append(f'\n[store.volumes.{vol.name}]\n')
                lines.append(f'path = "{vol.path}"\n')
                if vol.allocated_gb is not None:
                    lines.append(f'allocated_gb = {vol.allocated_gb}\n')

    (config.civex_dir / "config.toml").write_text("".join(lines))
