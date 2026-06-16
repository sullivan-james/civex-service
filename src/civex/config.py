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


@dataclass
class Config:
    project_root: Path
    db: DBConfig
    remote: RemoteConfig | None   # None when [remote] is absent — local-only mode

    @property
    def civex_dir(self) -> Path:
        return self.project_root / ".civex"

    @property
    def objects_dir(self) -> Path:
        return self.civex_dir / "objects"


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
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    remote: RemoteConfig | None = None
    if "remote" in data:
        remote = RemoteConfig(
            url=data["remote"]["url"],
            last_pushed_seq=int(data["remote"].get("last_pushed_seq", 0)),
            last_pulled_seq=int(data["remote"].get("last_pulled_seq", 0)),
            remote_civex=data["remote"].get("remote_civex", "civex"),
        )

    return Config(
        project_root=root,
        db=DBConfig(url=data["db"]["url"]),
        remote=remote,
    )


def save_config(config: Config) -> None:
    """Write config back to .civex/config.toml (used to update sync watermarks)."""
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

    (config.civex_dir / "config.toml").write_text("".join(lines))
