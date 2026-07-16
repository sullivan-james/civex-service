from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_init_config_has_valid_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tomllib

    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    config_text = (tmp_path / "_civex" / "config.toml").read_bytes()
    data = tomllib.loads(config_text.decode())
    assert "db" in data
    assert data["db"]["url"].startswith("sqlite:///")


def test_init_twice_warns_without_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    result = runner.invoke(app, ["init", "--sqlite", str(tmp_path)])
    assert result.exit_code == 0
    assert "already" in result.output.lower()
