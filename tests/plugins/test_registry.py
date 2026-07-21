"""PluginRegistration/PluginTier redesign (CIVEX-126/CIVEX-135).

Built-in plugins (new-style Tier0Plugin) and user/custom plugins (legacy
BasePlugin, unchanged _civex/plugins/*.py contract) must both register
uniformly as PluginRegistration(tier=BUILTIN, invoke(...) -> StepResult),
even though only built-ins were actually re-implemented against the new
interface this story.
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
    "civex.match_files_to_records": ["create_record", "update_record"],
    "civex.rows_to_records": ["create_record"],
    "civex.upsert_records": ["create_record", "update_record"],
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

    result = registration.invoke({}, config, _FakeCtx())
    assert isinstance(result, StepResult)
    assert result.outputs == {"value": "value"}
    assert result.logs == []
    assert result.error is None


_LEGACY_USER_PLUGIN_CODE = """\
from civex.plugins.base import BasePlugin, WorkflowContext

class Plugin(BasePlugin):
    id = "project.registry_test_plugin"
    name = "Registry Test Plugin"
    category = "test"

    def run(self, inputs, config, ctx: WorkflowContext) -> dict:
        return {"saw": inputs.get("value")}
"""


def test_legacy_user_plugin_also_registers_as_tier_builtin(tmp_path: Path):
    """Today's _civex/plugins/*.py contract (BasePlugin.run, exec_module
    discovery) is unchanged this story -- it still executes in-process, so
    it registers as tier BUILTIN too, wrapped into the same
    invoke()->StepResult shape as new-style built-ins."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "registry_test_plugin.py").write_text(_LEGACY_USER_PLUGIN_CODE)

    discover_user_plugins(plugins_dir)

    registration = get_plugin("project.registry_test_plugin")
    assert registration is not None
    assert registration.tier == PluginTier.BUILTIN
    assert registration.name == "Registry Test Plugin"
    assert registration.category == "test"
    assert registration.capabilities == []

    result = registration.invoke({"value": "x"}, registration.config_model(), None)
    assert isinstance(result, StepResult)
    assert result.outputs == {"saw": "x"}
