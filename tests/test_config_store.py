"""A project's settings have one text form (`render_config`/`parse_config`)
and one place they are kept (`ConfigStore`). Whoever keeps the text, a file
beside the project or a hosted service's database, reads it the same way."""

from __future__ import annotations

import tomllib
from pathlib import Path

from civex.config import (
    AIConfig,
    Config,
    DBConfig,
    FileConfigStore,
    PlacementConfig,
    StoreConfig,
    VolumeConfig,
    parse_config,
    render_config,
)
from civex.project import Project, scaffold_project


def _full_config(root: Path) -> Config:
    config = Config(
        project_root=root,
        db=DBConfig(url="sqlite:///x.db", docker_managed=True),
        store=StoreConfig(
            volumes={
                "default": VolumeConfig(name="default", path="_civex/objects"),
                "archive": VolumeConfig(
                    name="archive",
                    path="/mnt/archive",
                    allocated_gb=2.5,
                    id="vol-1",
                    state="readonly",
                ),
            },
            volume_queue=["archive", "default"],
            warn_below_pct=5.0,
            full_below_gb=2.0,
            placement={
                "0b7f9f9e-3a3c-4c7e-9b6a-6f8d6e1a2b3c": PlacementConfig(
                    volume="archive", on_unavailable="fail"
                )
            },
        ),
        ai=AIConfig(
            api_key="sk-test",
            model="some-model",
            provider="openai-compat",
            base_url="https://llm.example/v1",
        ),
    )
    config.plugins.default_timeout_seconds = 90.0
    config.ui.show_advanced = True
    config.map.tile_url = "https://tiles.example/{z}/{x}/{y}.png"
    config.map.attribution = "© Example"
    config.automation.paused = True
    config.identity.name = "Dr Example"
    config.sync.remote = "https://hub.example/p/me/study"
    config.sync.serve = True
    config.sync.paused = True
    config.sync.interval_seconds = 300
    config.sync.download_files = "opened"
    config.sync.library = "all"
    config.sync.collection_files = {"c1": "keep", "c2": "opened"}
    config.retention.purge_after_days = 7
    config.retention.auto_purge_deleted = True
    config.retention.audit_days = 365
    config.retention.run_days = 30
    return config


def test_the_text_form_round_trips_every_setting(tmp_path: Path):
    config = _full_config(tmp_path)
    text = render_config(config)
    assert parse_config(tomllib.loads(text), tmp_path) == config


def test_defaults_are_not_written(tmp_path: Path):
    text = render_config(
        Config(project_root=tmp_path, db=DBConfig(url="sqlite:///x.db"))
    )
    assert tomllib.loads(text) == {"db": {"url": "sqlite:///x.db"}}


def test_the_file_store_keeps_settings_in_config_toml(tmp_path: Path):
    scaffold_project(tmp_path)
    store = FileConfigStore(tmp_path)
    config = store.load()
    config.identity.name = "Dr Example"
    config.sync.serve = True
    store.save(config)

    assert store.load().identity.name == "Dr Example"
    text = (tmp_path / "_civex" / "config.toml").read_text()
    assert tomllib.loads(text)["identity"]["name"] == "Dr Example"


def test_a_flag_is_read_fresh_from_the_file(tmp_path: Path):
    """What another process just changed is seen at once, and the store
    answers False rather than failing when the file is unreadable."""
    scaffold_project(tmp_path)
    store = FileConfigStore(tmp_path)
    assert store.flag("sync", "serve") is False

    other = FileConfigStore(tmp_path)
    config = other.load()
    config.sync.serve = True
    config.automation.paused = True
    other.save(config)

    assert store.flag("sync", "serve") is True
    assert store.flag("automation", "paused") is True
    assert FileConfigStore(tmp_path / "nowhere").flag("sync", "serve") is False


def test_a_local_project_records_its_chosen_name(tmp_path: Path):
    scaffold_project(tmp_path)
    store = FileConfigStore(tmp_path)
    config = store.load()
    config.identity.name = "Dr Example"
    store.save(config)

    project = Project.local(store.load())
    assert project.actor == "Dr Example"
    assert isinstance(project.config_store, FileConfigStore)
    assert project.engine is None and project.migrated is False
