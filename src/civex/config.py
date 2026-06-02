"""
Project config — finds the nearest .civex/ directory (like git walks up from cwd)
and loads config.toml from it.

Minimal config.toml (local only):
    [db]
    url = "sqlite:///..."

With a remote (added by `civex remote add <url>`):
    [remote]
    url = "https://civex.example.com"
    token = "pat_abc123"   # optional
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import typer


@dataclass
class DBConfig:
    url: str


@dataclass
class RemoteConfig:
    url: str
    token: str | None = None


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
        typer.echo("Error: no civex project found. Run `civex init` to create one.", err=True)
        raise typer.Exit(1)

    config_path = root / ".civex" / "config.toml"
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    remote: RemoteConfig | None = None
    if "remote" in data:
        remote = RemoteConfig(
            url=data["remote"]["url"],
            token=data["remote"].get("token"),
        )

    return Config(
        project_root=root,
        db=DBConfig(url=data["db"]["url"]),
        remote=remote,
    )
