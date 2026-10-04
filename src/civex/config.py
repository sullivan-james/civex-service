"""
Project config — finds the nearest _civex/ directory (like git walks up from cwd)
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

import os
import threading
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from civex.domain.exceptions import ConfigError


@dataclass
class AIConfig:
    api_key: str
    model: str = "claude-sonnet-4-6"
    provider: str = "anthropic"  # "anthropic" | "openai-compat"
    base_url: str | None = None  # required when provider == "openai-compat"
    from_env: bool = (
        False  # True when key came from ANTHROPIC_API_KEY; not written to config.toml
    )


@dataclass
class LoggingConfig:
    level: str = "INFO"
    json_console: bool | None = None  # None = auto (pretty on a TTY, JSON otherwise)
    to_file: bool = True  # write rotating JSON logs to _civex/logs/


@dataclass
class TelemetryConfig:
    dsn: str | None = None  # opt-in Sentry DSN; None = disabled (default)
    environment: str = "local"


@dataclass
class PluginsConfig:
    # Wall-clock budget for a subprocess/container-tier plugin run, overridable
    # per-step via StepDef.timeout. Not consulted for tier BUILTIN.
    default_timeout_seconds: float = 60.0


@dataclass
class RetentionConfig:
    # Soft-deleted schemas/collections/records are eligible for permanent
    # purge once this many days have passed since deletion. Purging itself
    # is a separate, explicit action (`civex trash purge` / the API) --
    # this only controls what counts as "eligible".
    purge_after_days: int = 30


@dataclass
class UIConfig:
    # Surfaces the Terminal/YAML-workflow-editor/plugin-editor nav group by
    # default. Off for new projects — those are power-user escape hatches,
    # not the researcher-facing front door.
    show_advanced: bool = False


@dataclass
class MapConfig:
    # An XYZ tile URL for the location editor's street-level map, e.g.
    # "https://tile.example.org/{z}/{x}/{y}.png". Unset (the default) keeps
    # the editor on its bundled coastlines, which need no account and work
    # offline. Whoever sets this is responsible for the tile provider's
    # terms of use (the public OpenStreetMap servers, for one, rule out
    # heavy use).
    tile_url: str | None = None
    attribution: str | None = None


@dataclass
class DBConfig:
    url: str
    docker_managed: bool = False


@dataclass
class RemoteConfig:
    url: str
    last_pushed_seq: int = 0
    last_pulled_seq: int = 0
    remote_civex: str = "civex"  # path to civex on the remote (for SSH transport)
    last_pushed_at: datetime | None = None
    last_pulled_at: datetime | None = None


@dataclass
class VolumeConfig:
    name: str
    path: (
        str  # raw string — may be relative (resolved against project root) or absolute
    )
    allocated_gb: float | None = None  # None = unlimited
    # Identity: also written to a `.civex-volume` marker in the volume's root,
    # so the drive is recognised wherever it is mounted and a different drive
    # at the same path is not mistaken for it. Set by `store add` / `store
    # adopt`; None for a volume that predates identities (checked by path only).
    id: str | None = None
    state: str = "active"  # active | readonly | retired


@dataclass
class PlacementConfig:
    """A collection's home volume. Keyed in `StoreConfig.placement` by the
    collection's id, so renaming a collection changes nothing here."""

    volume: str  # a key of StoreConfig.volumes
    on_unavailable: str = "spill"  # domain.placement: spill | fail


@dataclass
class StoreConfig:
    volumes: dict[str, VolumeConfig]
    volume_queue: list[str]
    warn_below_pct: float = (
        10.0  # show warning in UI when less than this % of space remains
    )
    full_below_gb: float = (
        1.0  # treat volume as full below this disk headroom (absolute)
    )
    # collection id -> home volume. Per-machine like the volumes it names, so
    # it lives here and not on the collection (which dump/sync carry elsewhere).
    placement: dict[str, PlacementConfig] = field(default_factory=dict)


def _default_store(project_root: Path) -> StoreConfig:
    default_vol = VolumeConfig(name="default", path="_civex/objects")
    return StoreConfig(volumes={"default": default_vol}, volume_queue=["default"])


@dataclass
class Config:
    project_root: Path
    db: DBConfig
    remote: RemoteConfig | None  # None when [remote] is absent — local-only mode
    store: StoreConfig | None = (
        None  # None until first access; use store_config property
    )
    ai: AIConfig | None = None  # None when [ai] is absent and ANTHROPIC_API_KEY not set
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    map: MapConfig = field(default_factory=MapConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)

    @property
    def civex_dir(self) -> Path:
        return self.project_root / "_civex"

    @property
    def objects_dir(self) -> Path:
        return self.civex_dir / "objects"

    @property
    def store_config(self) -> StoreConfig:
        if self.store is None:
            self.store = _default_store(self.project_root)
        return self.store


def find_project_root() -> Path | None:
    """Walk up from cwd looking for a _civex directory."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        if (directory / "_civex").is_dir():
            return directory
    return None


def _retry_sharing_violation(action, attempts: int = 40, delay: float = 0.005):
    """Run `action()`; on Windows, a file that another thread has open for
    reading or replacing raises PermissionError for a moment, so try again.
    Elsewhere (and when it persists) the error is real and propagates."""
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(delay)


def load_config() -> Config:
    root = find_project_root()
    if root is None:
        raise ConfigError("No civex project found. Run `civex init` to create one.")

    config_path = root / "_civex" / "config.toml"

    def _read() -> dict:
        with open(config_path, "rb") as f:
            return tomllib.load(f)

    try:
        data = _retry_sharing_violation(_read)
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
                id=vcfg.get("id"),
                state=vcfg.get("state", "active"),
            )
            for name, vcfg in raw_vols.items()
        }
        if not volumes:
            volumes = {"default": VolumeConfig(name="default", path="_civex/objects")}
        queue = sd.get("volume_queue", list(volumes.keys()))
        placement = {
            cid: PlacementConfig(
                volume=pcfg["volume"],
                on_unavailable=pcfg.get("on_unavailable", "spill"),
            )
            for cid, pcfg in sd.get("placement", {}).items()
        }
        store = StoreConfig(
            volumes=volumes,
            volume_queue=queue,
            warn_below_pct=float(sd.get("warn_below_pct", 10.0)),
            full_below_gb=float(sd.get("full_below_gb", 1.0)),
            placement=placement,
        )

    ai: AIConfig | None = None
    ai_data = data.get("ai", {})
    import os

    config_key = ai_data.get("api_key")
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    api_key = config_key or env_key
    if api_key:
        ai = AIConfig(
            api_key=api_key,
            model=ai_data.get("model", "claude-sonnet-4-6"),
            provider=ai_data.get("provider", "anthropic"),
            base_url=ai_data.get("base_url") or None,
            from_env=(not config_key and bool(env_key)),
        )

    log_data = data.get("logging", {})
    logging_cfg = LoggingConfig(
        level=str(log_data.get("level", "INFO")),
        json_console=log_data.get("json_console"),
        to_file=bool(log_data.get("to_file", True)),
    )

    tel_data = data.get("telemetry", {})
    telemetry_cfg = TelemetryConfig(
        dsn=tel_data.get("dsn") or os.environ.get("CIVEX_SENTRY_DSN"),
        environment=str(tel_data.get("environment", "local")),
    )

    plugins_data = data.get("plugins", {})
    plugins_cfg = PluginsConfig(
        default_timeout_seconds=float(
            plugins_data.get("default_timeout_seconds", 60.0)
        ),
    )

    ui_data = data.get("ui", {})
    ui_cfg = UIConfig(show_advanced=bool(ui_data.get("show_advanced", False)))

    map_data = data.get("map", {})
    map_cfg = MapConfig(
        tile_url=map_data.get("tile_url") or None,
        attribution=map_data.get("attribution") or None,
    )

    retention_data = data.get("retention", {})
    retention_cfg = RetentionConfig(
        purge_after_days=int(retention_data.get("purge_after_days", 30)),
    )

    return Config(
        project_root=root,
        db=DBConfig(
            url=data["db"]["url"],
            docker_managed=bool(data["db"].get("docker_managed", False)),
        ),
        remote=remote,
        store=store,
        ai=ai,
        logging=logging_cfg,
        telemetry=telemetry_cfg,
        plugins=plugins_cfg,
        ui=ui_cfg,
        map=map_cfg,
        retention=retention_cfg,
    )


def _ts(s: str) -> str:
    """Escape a string for use inside a TOML double-quoted value."""
    return s.replace("\\", "/")  # backslashes → forward slashes (valid on all OSes)


def _tv(s: str) -> str:
    """A TOML basic string for free text that may contain quotes."""
    import json

    return json.dumps(s)


def _tk(s: str) -> str:
    """Return a TOML key segment, quoted if necessary."""
    import re

    if re.fullmatch(r"[A-Za-z0-9_-]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_config(config: Config) -> None:
    """Write config back to _civex/config.toml with backup/restore on failure."""
    lines: list[str] = [
        "[db]\n",
        f'url = "{_ts(config.db.url)}"\n',
    ]
    if config.db.docker_managed:
        lines.append("docker_managed = true\n")
    if config.remote:
        lines += ["\n[remote]\n", f'url = "{_ts(config.remote.url)}"\n']
        if config.remote.remote_civex != "civex":
            lines.append(f'remote_civex = "{_ts(config.remote.remote_civex)}"\n')
        lines.append(f"last_pushed_seq = {config.remote.last_pushed_seq}\n")
        lines.append(f"last_pulled_seq = {config.remote.last_pulled_seq}\n")
        if config.remote.last_pushed_at:
            lines.append(
                f'last_pushed_at = "{config.remote.last_pushed_at.isoformat()}"\n'
            )
        if config.remote.last_pulled_at:
            lines.append(
                f'last_pulled_at = "{config.remote.last_pulled_at.isoformat()}"\n'
            )

    if config.ai and not config.ai.from_env:
        lines += ["\n[ai]\n", f'api_key = "{_ts(config.ai.api_key)}"\n']
        lines.append(f'model = "{config.ai.model}"\n')
        if config.ai.provider != "anthropic":
            lines.append(f'provider = "{config.ai.provider}"\n')
        if config.ai.base_url:
            lines.append(f'base_url = "{_ts(config.ai.base_url)}"\n')

    sc = config.store
    if sc is not None:
        is_default = (
            list(sc.volumes.keys()) == ["default"]
            and sc.volumes["default"].path == "_civex/objects"
            and sc.volumes["default"].allocated_gb is None
            and sc.volumes["default"].id is None
            and sc.volumes["default"].state == "active"
            and sc.volume_queue == ["default"]
            and sc.warn_below_pct == 10.0
            and sc.full_below_gb == 1.0
            and not sc.placement
        )
        if not is_default:
            queue_str = ", ".join(f'"{_ts(n)}"' for n in sc.volume_queue)
            lines += [
                "\n[store]\n",
                f"volume_queue = [{queue_str}]\n",
                f"warn_below_pct = {sc.warn_below_pct}\n",
                f"full_below_gb = {sc.full_below_gb}\n",
            ]
            for vol in sc.volumes.values():
                key = f"store.volumes.{_tk(vol.name)}"
                lines.append(f"\n[{key}]\n")
                lines.append(f'path = "{_ts(vol.path)}"\n')
                if vol.allocated_gb is not None:
                    lines.append(f"allocated_gb = {vol.allocated_gb}\n")
                if vol.id:
                    lines.append(f'id = "{_ts(vol.id)}"\n')
                if vol.state != "active":
                    lines.append(f'state = "{_ts(vol.state)}"\n')
            for cid, place in sc.placement.items():
                lines.append(f"\n[store.placement.{_tk(cid)}]\n")
                lines.append(f'volume = "{_ts(place.volume)}"\n')
                if place.on_unavailable != "spill":
                    lines.append(f'on_unavailable = "{_ts(place.on_unavailable)}"\n')

    if config.plugins.default_timeout_seconds != 60.0:
        lines += [
            "\n[plugins]\n",
            f"default_timeout_seconds = {config.plugins.default_timeout_seconds}\n",
        ]

    if config.ui.show_advanced:
        lines += ["\n[ui]\n", "show_advanced = true\n"]

    if config.map.tile_url or config.map.attribution:
        lines.append("\n[map]\n")
        if config.map.tile_url:
            lines.append(f"tile_url = {_tv(config.map.tile_url)}\n")
        if config.map.attribution:
            lines.append(f"attribution = {_tv(config.map.attribution)}\n")

    if config.retention.purge_after_days != 30:
        lines += [
            "\n[retention]\n",
            f"purge_after_days = {config.retention.purge_after_days}\n",
        ]

    config_path = config.civex_dir / "config.toml"
    content = "".join(lines)

    # Validate the generated TOML before touching the file.
    try:
        import tomllib

        tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"Generated config is invalid TOML: {e}\n\nContent:\n{content}"
        ) from e

    # Write a temporary file beside it, check that parses, then swap it in with
    # one atomic rename. Every request reads this file, and a transfer rewrites
    # it while freezing a volume, so a reader must see the old file or the new
    # one, never half of either; and if anything fails the original is untouched.
    tmp = config_path.with_name(
        f"{config_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp.write_text(content, encoding="utf-8")
        with open(tmp, "rb") as f:
            tomllib.load(f)
        _retry_sharing_violation(lambda: os.replace(tmp, config_path))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ConfigError(
            f"Failed to write config (the original is untouched): {e}"
        ) from e
