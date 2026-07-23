"""`civex plugin list`/`plugin info` (CIVEX-144) -- both read
PluginService.list_registered(), the same declared contract every other
surface reads, so there's nothing tier-specific or hand-maintained to test
here beyond correct rendering.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_plugin_list_includes_builtins(project_dir: Path) -> None:
    result = runner.invoke(app, ["plugin", "list"])
    assert result.exit_code == 0
    assert "civex.get_field" in result.output
    assert "built-in" in result.output


def test_plugin_info_shows_description_inputs_outputs_and_config(
    project_dir: Path,
) -> None:
    result = runner.invoke(app, ["plugin", "info", "civex.get_field"])
    assert result.exit_code == 0
    assert "Get Field" in result.output
    assert "civex.get_field" in result.output
    assert "value" in result.output  # declared output name
    assert "field" in result.output  # declared config key


def test_plugin_info_shows_capabilities_when_declared(project_dir: Path) -> None:
    result = runner.invoke(app, ["plugin", "info", "civex.save_field"])
    assert result.exit_code == 0
    assert "update_record" in result.output


def test_plugin_info_unknown_plugin_exits_nonzero(project_dir: Path) -> None:
    result = runner.invoke(app, ["plugin", "info", "civex.does_not_exist"])
    assert result.exit_code == 1
    assert "not found" in result.output
