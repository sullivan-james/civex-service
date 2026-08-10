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
class UIConfig:
    # Surfaces the Terminal/YAML-workflow-editor/plugin-editor nav group by
    # default. Off for new projects — those are power-user escape hatches,
    # not the researcher-facing front door.
    show_advanced: bool = False


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


def load_config() -> Config:
    root = find_project_root()
    if root is None:
        raise ConfigError("No civex project found. Run `civex init` to create one.")

    config_path = root / "_civex" / "config.toml"
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
            volumes = {"default": VolumeConfig(name="default", path="_civex/objects")}
        queue = sd.get("volume_queue", list(volumes.keys()))
        store = StoreConfig(
            volumes=volumes,
            volume_queue=queue,
            warn_below_pct=float(sd.get("warn_below_pct", 10.0)),
            full_below_gb=float(sd.get("full_below_gb", 1.0)),
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
    )


def _ts(s: str) -> str:
    """Escape a string for use inside a TOML double-quoted value."""
    return s.replace("\\", "/")  # backslashes → forward slashes (valid on all OSes)


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
            and sc.volume_queue == ["default"]
            and sc.warn_below_pct == 10.0
            and sc.full_below_gb == 1.0
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

    if config.plugins.default_timeout_seconds != 60.0:
        lines += [
            "\n[plugins]\n",
            f"default_timeout_seconds = {config.plugins.default_timeout_seconds}\n",
        ]

    if config.ui.show_advanced:
        lines += ["\n[ui]\n", "show_advanced = true\n"]

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

    # Atomic-ish write: backup → write → verify read-back → restore on failure.
    backup = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    try:
        config_path.write_text(content, encoding="utf-8")
        with open(config_path, "rb") as f:
            tomllib.load(f)
    except Exception as e:
        if backup is not None:
            config_path.write_text(backup, encoding="utf-8")
        raise ConfigError(f"Failed to write config (original restored): {e}") from e
