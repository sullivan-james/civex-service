"""The Desktop shortcut that starts civex."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civex import launcher
from civex.domain.exceptions import ConfigError


@pytest.fixture
def desktop(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "Desktop"
    d.mkdir()
    monkeypatch.setattr(launcher, "desktop_dir", lambda: d)
    return d


def test_shortcut_runs_serve_open_in_the_project(tmp_path, desktop, monkeypatch):
    monkeypatch.setattr(launcher, "_platform", lambda: "linux")
    project = tmp_path / "my study"
    project.mkdir()
    path = launcher.create_shortcut(project)

    assert path.parent == desktop and path.name == "Civex - my study.desktop"
    text = path.read_text()
    assert f"Path={project.resolve()}" in text
    assert "serve" in text and "--open" in text and sys.executable in text
    assert "Terminal=true" in text
    assert path.stat().st_mode & 0o111  # executable
    assert launcher.shortcut_exists(project)


def test_each_platform_gets_its_own_kind_of_file(tmp_path, desktop, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    for platform, suffix in [("macos", ".command"), ("windows", ".bat")]:
        monkeypatch.setattr(launcher, "_platform", lambda p=platform: p)
        path = launcher.create_shortcut(project)
        assert path.suffix == suffix
        assert str(project.resolve()) in path.read_text()


def test_no_desktop_is_a_clear_error(tmp_path, monkeypatch):
    def none():
        raise ConfigError("There is no Desktop folder to put a shortcut in.")

    monkeypatch.setattr(launcher, "desktop_dir", none)
    assert launcher.shortcut_exists(tmp_path) is False
    with pytest.raises(ConfigError):
        launcher.create_shortcut(tmp_path)


def test_settings_endpoint_creates_the_shortcut(client: TestClient, desktop):
    before = client.get("/api/settings/shortcut").json()
    assert before["exists"] is False

    after = client.post("/api/settings/shortcut").json()
    assert after["exists"] is True
    assert Path(after["path"]).parent == desktop
    assert client.get("/api/settings/shortcut").json()["exists"] is True
