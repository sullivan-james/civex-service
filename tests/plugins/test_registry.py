"""PluginRegistration/PluginTier redesign (CIVEX-126) and the Tier 1
subprocess runtime (CIVEX-127). Built-in plugins (Tier0Plugin, in-process)
and user/custom plugins (civex_plugin_sdk.Plugin, uv-managed subprocess)
both register uniformly as PluginRegistration(invoke(...) -> StepResult),
but resolve to different tiers -- BUILTIN vs. SUBPROCESS.
"""

from __future__ import annotations

from pathlib import Path

from civex.plugins.base import PluginTier, StepResult
from civex.plugins.registry import discover_user_plugins, get_plugin

_ALL_BUILTIN_IDS_AND_CAPABILITIES = {
    "civex.get_field": [],
    "civex.save_field": ["update_record"],
    "civex.save_fields": ["update_record"],
    "civex.load_file": ["get_file"],
    "civex.load_file_list": [],
    "civex.extract_from_filename": [],
    "civex.load_csv": [],
    "civex.create_records_from_files": ["create_record"],
    "civex.match_files_to_records": ["create_record", "update_record", "find_records"],
    "civex.rows_to_records": ["create_record"],
    "civex.upsert_records": ["create_record", "update_record", "find_records"],
}


def test_all_builtins_register_with_tier_builtin_and_declared_capabilities():
    for plugin_id, capabilities in _ALL_BUILTIN_IDS_AND_CAPABILITIES.items():
        registration = get_plugin(plugin_id)
        assert registration is not None, f"{plugin_id} not registered"
        assert registration.tier == PluginTier.BUILTIN
        assert registration.capabilities == capabilities
        assert registration.id == plugin_id


def test_builtin_invoke_returns_step_result_wrapping_outputs():
    registration = get_plugin("civex.get_field")
    assert registration is not None
    config = registration.config_model(field="anything")

    class _FakeRecord:
        data = {"anything": "value"}

    class _FakeCtx:
        record = _FakeRecord()

    result = registration.invoke({}, config, _FakeCtx(), 60.0)
    assert isinstance(result, StepResult)
    assert result.outputs == {"value": "value"}
    assert result.logs == []
    assert result.error is None


_USER_PLUGIN_CODE = """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.registry_test_plugin"
    name = "Registry Test Plugin"
    category = "test"
    capabilities = ["commit"]

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {"saw": inputs.get("value")}

if __name__ == "__main__":
    serve(Plugin)
"""


def test_user_plugin_registers_as_tier_subprocess(tmp_path: Path):
    """A _civex/plugins/*.py file is discovered by spawning it and asking it
    to describe itself (CIVEX-127), not by exec_module-ing it in-process --
    it registers as tier SUBPROCESS, with capabilities/config_schema coming
    from its own describe response."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "registry_test_plugin.py").write_text(_USER_PLUGIN_CODE)

    discover_user_plugins(plugins_dir)

    registration = get_plugin("project.registry_test_plugin")
    assert registration is not None
    assert registration.tier == PluginTier.SUBPROCESS
    assert registration.name == "Registry Test Plugin"
    assert registration.category == "test"
    assert registration.capabilities == ["commit"]
    assert registration.config_schema is not None

    result = registration.invoke(
        {"value": "x"}, registration.config_model(), None, 20.0
    )
    assert isinstance(result, StepResult)
    assert result.outputs == {"saw": "x"}


def test_user_plugin_discovery_is_cached_within_process(tmp_path: Path, monkeypatch):
    """Re-running discover_user_plugins against an already-registered file
    shouldn't re-spawn `uv run` -- expensive, and unnecessary since nothing
    about revalidating a changed file is in scope here (CIVEX-128)."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "cached_plugin.py").write_text(
        _USER_PLUGIN_CODE.replace(
            "project.registry_test_plugin", "project.cached_plugin"
        )
    )

    discover_user_plugins(plugins_dir)
    assert get_plugin("project.cached_plugin") is not None

    from civex.plugins import subprocess_runtime

    def _boom(*args, **kwargs):
        raise AssertionError("describe_plugin should not be called again")

    monkeypatch.setattr(subprocess_runtime, "describe_plugin", _boom)
    discover_user_plugins(plugins_dir)  # must not raise
