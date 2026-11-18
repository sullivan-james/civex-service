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
    assert "write_records" in result.output


def test_plugin_info_unknown_plugin_exits_nonzero(project_dir: Path) -> None:
    result = runner.invoke(app, ["plugin", "info", "civex.does_not_exist"])
    assert result.exit_code == 1
    assert "not found" in result.output


_PLUGIN = """\
# /// script
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.checked"
    name = "Checked"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {}

if __name__ == "__main__":
    serve(Plugin)
"""


def test_plugin_check_says_a_missing_header_and_write_adds_it(
    project_dir: Path,
) -> None:
    plugins = project_dir / "_civex" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (plugins / "checked.py").write_text(_PLUGIN)

    result = runner.invoke(app, ["plugin", "check", "checked.py"])
    assert result.exit_code == 1
    assert "no [tool.civex] header" in result.output

    result = runner.invoke(app, ["plugin", "check", "checked", "--write"])
    assert result.exit_code == 0, result.output
    assert "Header written" in result.output
    assert "# [tool.civex]" in (plugins / "checked.py").read_text()

    result = runner.invoke(app, ["plugin", "check", "checked.py"])
    assert result.exit_code == 0
    assert "says what the code does" in result.output
