"""PluginRegistration/PluginTier redesign (CIVEX-126) and the Tier 1
subprocess runtime (CIVEX-127). Built-in plugins (Tier0Plugin, in-process)
and user/custom plugins (civex_plugin_sdk.Plugin, uv-managed subprocess)
both register uniformly as PluginRegistration(invoke(...) -> StepResult),
but resolve to different tiers -- BUILTIN vs. SUBPROCESS.
"""

from __future__ import annotations

from pathlib import Path

from civex_plugin_sdk.plugin_base import IO_TYPES

from civex.plugins.base import PluginTier, StepResult
from civex.plugins.registry import all_plugins, discover_user_plugins, get_plugin

# Declared step-wiring contract per built-in (CIVEX-141), as
# {plugin_id: (input names, output names)}. Duplicated here deliberately
# rather than read back off the registration: this table is what a workflow
# author is promised, so a change to a built-in's inputs/outputs has to be a
# visible, intentional edit to an expected value -- exactly like
# _ALL_BUILTIN_IDS_AND_CAPABILITIES above. Whether those declarations match
# what invoke() actually returns is enforced separately, in test_builtins.py.
_BUILTIN_CONTRACTS = {
    "civex.get_field": ((), ("value",)),
    "civex.save_field": (("value",), ()),
    "civex.save_fields": (("updates",), ()),
    "civex.load_file": ((), ("bytes", "filename", "sha256")),
    "civex.load_file_list": ((), ("files",)),
    "civex.extract_from_filename": ((), ("value", "filename", "extracted")),
    "civex.load_csv": (("bytes",), ("table",)),
    "civex.create_records_from_files": (("files",), ("created", "skipped")),
    "civex.match_files_to_records": (("files",), ("created", "updated", "unmatched")),
    "civex.rows_to_records": (("table",), ("created",)),
    "civex.upsert_records": (("table",), ("created", "updated")),
}

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


def test_all_builtins_declare_their_step_wiring_contract():
    for plugin_id, (inputs, outputs) in _BUILTIN_CONTRACTS.items():
        registration = get_plugin(plugin_id)
        assert registration is not None, f"{plugin_id} not registered"
        assert tuple(spec.name for spec in registration.inputs) == inputs
        assert tuple(spec.name for spec in registration.outputs) == outputs


def test_every_builtin_declares_a_description():
    """PluginService.list_registered() showed a blank description for every
    plugin before CIVEX-141 (nothing set one, and the registry fell back to
    ""), which is what made the CLI/API/UI plugin listings useless."""
    for plugin_id in _BUILTIN_CONTRACTS:
        registration = get_plugin(plugin_id)
        assert registration is not None
        assert registration.description.strip(), f"{plugin_id} has no description"


def test_every_builtin_declares_a_contract_in_both_directions():
    """`[]` ("takes no inputs") and None ("hasn't said") are distinct, and
    only the former lets CIVEX-142 reject bad wiring. Built-ins must always
    be the former -- a built-in silently reverting to None would quietly
    disable save-time validation for every workflow using it."""
    for plugin_id in _BUILTIN_CONTRACTS:
        registration = get_plugin(plugin_id)
        assert registration is not None
        assert registration.inputs is not None, f"{plugin_id} declares no inputs"
        assert registration.outputs is not None, f"{plugin_id} declares no outputs"


def test_builtin_io_declarations_use_the_known_type_vocabulary():
    """IOSpec.type is an unconstrained str on the wire so an older host can
    still read a newer plugin's describe output -- which means in-repo
    declarations are the only place a typo'd type gets caught."""
    for plugin_id, registration in all_plugins().items():
        for spec in [*(registration.inputs or []), *(registration.outputs or [])]:
            assert spec.type in IO_TYPES, (
                f"{plugin_id}.{spec.name} declares unknown type {spec.type!r}"
            )


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
from civex_plugin_sdk import Ctx, IOSpec, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.registry_test_plugin"
    name = "Registry Test Plugin"
    description = "Echoes its input back as an output."
    category = "test"
    capabilities = ["commit"]
    inputs = [IOSpec(name="value", type="any")]
    outputs = [IOSpec(name="saw", type="any")]

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
    # Same contract fields as a built-in, reaching the registration by a
    # different route (a real describe round-trip over the wire protocol
    # rather than class-attribute reads) -- this is the "regardless of tier"
    # part of CIVEX-141.
    assert registration.description == "Echoes its input back as an output."
    assert [spec.name for spec in registration.inputs] == ["value"]
    assert [spec.name for spec in registration.outputs] == ["saw"]

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
