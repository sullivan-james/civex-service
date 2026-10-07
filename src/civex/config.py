"""
Project config — finds the nearest _civex/ directory (like git walks up from cwd)
and loads config.toml from it.

Minimal config.toml (local only):
    [db]
    url = "sqlite:///..."

A `[remote]` table written by civex before 1.2 is ignored (and dropped on the
next save): the old push/pull sync was removed.
"""

from __future__ import annotations

import os
import threading
import time
import tomllib
from dataclasses import dataclass, field
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


def _interval(value: object) -> int:
    """Seconds between automatic syncs; 0 means never (only when asked)."""
    seconds = int(value)  # type: ignore[call-overload]
    return 0 if seconds <= 0 else max(5, seconds)


@dataclass
class IdentityConfig:
    """Who changes made in this project are recorded as. None: the operating-system user. It is only a label
    (history says who, unverified); a synced change is attributed by the
    authority from the device's token."""

    name: str | None = None


@dataclass
class SyncConfig:
    """Keeping this project in step with other copies of it (CIVEX-305): one
    instance is the *authority* and every other device follows it."""

    # The authority this project syncs to, e.g. "https://civex.example.org".
    # None: not synced. The token is not here (config.toml is shared and
    # backed up); it lives in the user's own state, see `civex.user_state`.
    remote: str | None = None
    # This instance is an authority: it accepts changes from devices that hold
    # a token, and no one else may reach anything but `/api/sync/v1`.
    serve: bool = False
    # Stops the background sync (a manual sync still works). Kept here so every
    # process sees it, like `[automation] paused`.
    paused: bool = False
    # How often the background sync looks for changes, in seconds. 0 = never:
    # it syncs only when asked (Sync now, `civex sync`).
    interval_seconds: int = 60
    # Which files a device keeps a copy of (`DOWNLOAD_MODES`): "all" fetches
    # every file the project's records cite in the background, a few at a time;
    # "opened" fetches one only when it is opened or exported (for a computer
    # short of space). Either way a file is fetched on demand.
    download_files: str = "all"
    # Per collection (by id), overriding `download_files` for its files: "keep"
    # (a copy stays on this computer, fetched in the background) or "opened"
    # (fetched when opened or exported; its copies can be removed to free
    # space). Keyed by id like placement, so a rename changes nothing.
    collection_files: dict[str, str] = field(default_factory=dict)


DOWNLOAD_MODES = ("all", "opened")
COLLECTION_FILE_MODES = ("keep", "opened")


@dataclass
class AutomationConfig:
    # The kill switch for workflows. While true nothing new starts: triggers
    # enqueue nothing, queued runs aren't picked up, and manual runs are
    # refused. Set by `civex automation stop` / the Stop button (which also
    # cancels what is waiting or running) and cleared by Resume. Kept here, in
    # config.toml, so it survives a restart and every process (the server, a
    # terminal) sees the same answer.
    paused: bool = False


@dataclass
class RetentionConfig:
    """How long things are kept, for the clean-up pass (`RetentionService`) to
    work through. Nothing here runs by itself: a person or a schedule starts the
    clean-up, and every default keeps everything, as before."""

    # Soft-deleted schemas/collections/records can be restored for this many
    # days. Only when `auto_purge_deleted` is on does a clean-up permanently
    # delete them after that; otherwise purging stays an explicit action.
    purge_after_days: int = 30
    auto_purge_deleted: bool = False
    # Keep change history (the audit log) this many days; None = forever.
    audit_days: int | None = None
    # Keep finished workflow runs, with their step logs, this many days;
    # None = forever.
    run_days: int | None = None


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
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)

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


def _optional_days(value: object) -> int | None:
    """A retention period in days from the file: a positive whole number, or
    nothing (0 or absent) for keep-forever."""
    if value is None:
        return None
    days = int(value)  # type: ignore[call-overload]
    return days if days > 0 else None


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
        auto_purge_deleted=bool(retention_data.get("auto_purge_deleted", False)),
        audit_days=_optional_days(retention_data.get("audit_days")),
        run_days=_optional_days(retention_data.get("run_days")),
    )

    automation_cfg = AutomationConfig(
        paused=bool(data.get("automation", {}).get("paused", False)),
    )

    identity_name = str(data.get("identity", {}).get("name") or "").strip()[:100]
    sync_data = data.get("sync", {})
    sync_cfg = SyncConfig(
        remote=(str(sync_data["remote"]).rstrip("/") or None)
        if sync_data.get("remote")
        else None,
        serve=bool(sync_data.get("serve", False)),
        paused=bool(sync_data.get("paused", False)),
        interval_seconds=_interval(sync_data.get("interval_seconds", 60)),
        download_files=(
            str(sync_data.get("download_files"))
            if sync_data.get("download_files") in DOWNLOAD_MODES
            else "all"
        ),
        collection_files={
            str(cid): str(mode)
            for cid, mode in (sync_data.get("collection_files") or {}).items()
            if mode in COLLECTION_FILE_MODES
        },
    )

    return Config(
        project_root=root,
        db=DBConfig(
            url=data["db"]["url"],
            docker_managed=bool(data["db"].get("docker_managed", False)),
        ),
        store=store,
        ai=ai,
        logging=logging_cfg,
        telemetry=telemetry_cfg,
        plugins=plugins_cfg,
        ui=ui_cfg,
        map=map_cfg,
        retention=retention_cfg,
        automation=automation_cfg,
        sync=sync_cfg,
        identity=IdentityConfig(name=identity_name or None),
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


def read_automation_paused(civex_dir: Path) -> bool:
    """Whether automation is paused, read straight from `config.toml`. Cheap
    and cwd-independent, because every trigger, queue claim and workflow step
    asks, and a worker in another process must see a Stop at once."""
    try:
        data = tomllib.loads((civex_dir / "config.toml").read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return bool(data.get("automation", {}).get("paused", False))


def read_sync_flag(civex_dir: Path, key: str) -> bool:
    """A boolean from `[sync]` (`serve`, `paused`), read straight from
    `config.toml`: cheap and cwd-independent, for what is asked per request or
    per background tick."""
    try:
        data = tomllib.loads((civex_dir / "config.toml").read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return bool(data.get("sync", {}).get(key, False))


def save_config(config: Config) -> None:
    """Write config back to _civex/config.toml with backup/restore on failure."""
    lines: list[str] = [
        "[db]\n",
        f'url = "{_ts(config.db.url)}"\n',
    ]
    if config.db.docker_managed:
        lines.append("docker_managed = true\n")

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

    if config.automation.paused:
        lines += ["\n[automation]\n", "paused = true\n"]

    if config.identity.name:
        lines += ["\n[identity]\n", f"name = {_tv(config.identity.name)}\n"]

    sync = config.sync
    if (
        sync.remote
        or sync.serve
        or sync.paused
        or sync.interval_seconds != 60
        or sync.download_files != "all"
    ):
        lines.append("\n[sync]\n")
        if sync.remote:
            lines.append(f"remote = {_tv(sync.remote)}\n")
        if sync.serve:
            lines.append("serve = true\n")
        if sync.paused:
            lines.append("paused = true\n")
        if sync.interval_seconds != 60:
            lines.append(f"interval_seconds = {sync.interval_seconds}\n")
        if sync.download_files != "all":
            lines.append(f"download_files = {_tv(sync.download_files)}\n")
    if sync.collection_files:
        lines.append("\n[sync.collection_files]\n")
        for cid, mode in sorted(sync.collection_files.items()):
            lines.append(f"{_tv(cid)} = {_tv(mode)}\n")

    retention = config.retention
    retention_lines = []
    if retention.purge_after_days != 30:
        retention_lines.append(f"purge_after_days = {retention.purge_after_days}\n")
    if retention.auto_purge_deleted:
        retention_lines.append("auto_purge_deleted = true\n")
    if retention.audit_days is not None:
        retention_lines.append(f"audit_days = {retention.audit_days}\n")
    if retention.run_days is not None:
        retention_lines.append(f"run_days = {retention.run_days}\n")
    if retention_lines:
        lines += ["\n[retention]\n", *retention_lines]

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
