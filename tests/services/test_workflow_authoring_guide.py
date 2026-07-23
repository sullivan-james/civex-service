"""GetWorkflowAuthoringGuideTool's built-in plugin reference table (CIVEX-144)
is generated from PluginService.list_registered() per call rather than
hand-maintained -- these tests assert it can't drift from what a plugin's
declared contract actually is, which is the whole reason the old hardcoded
table was a problem in the first place.
"""

from __future__ import annotations

from civex.context import AppContext
from civex.services.ai.tools.base import AiToolContext
from civex.services.ai.tools.builtins.workflow_tools import (
    GetWorkflowAuthoringGuideTool,
    _format_builtin_reference,
)


def _tool_ctx(ctx: AppContext) -> AiToolContext:
    return AiToolContext(
        schema_svc=ctx.schema_svc,
        dataset_svc=ctx.dataset_svc,
        record_svc=ctx.record_svc,
        job_svc=ctx.job_svc,
        workflow_svc=ctx.workflow_svc,
        plugin_svc=ctx.plugin_svc,
        _app_ctx=ctx,
    )


def test_guide_lists_every_builtin_with_its_declared_config_and_io(
    ctx: AppContext,
) -> None:
    guide = GetWorkflowAuthoringGuideTool().run({}, _tool_ctx(ctx))
    for plugin_id in ctx.plugin_svc.list_registered():
        if plugin_id["builtin"]:
            assert plugin_id["id"] in guide

    # get_field: a single required config key, one declared output.
    assert "civex.get_field" in guide
    assert "config: {field}" in guide
    assert "outputs: value" in guide

    # extract_from_filename: required field first, the rest optional (each
    # has a default and so isn't in the config schema's `required` list).
    assert "config: {field, pattern?, output_type?, date_format?}" in guide


def test_guide_never_lists_a_custom_plugin_in_the_builtin_table(
    ctx: AppContext,
) -> None:
    """The reference table is scoped to built-ins -- a user's custom
    (subprocess-tier) plugin has its own contract surfaced through
    list_plugins, not baked into this static-format section."""
    custom_code = """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.my_custom_plugin"
    name = "My Custom Plugin"

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {}

if __name__ == "__main__":
    serve(Plugin)
"""
    ctx.plugin_svc.save("my_custom_plugin", custom_code)
    guide = GetWorkflowAuthoringGuideTool().run({}, _tool_ctx(ctx))
    assert "project.my_custom_plugin" not in guide


def test_format_builtin_reference_marks_optional_keys_with_question_mark():
    registered = [
        {
            "id": "civex.example",
            "builtin": True,
            "config_schema": {
                "properties": {"required_key": {}, "optional_key": {"default": 1}},
                "required": ["required_key"],
            },
            "inputs": [],
            "outputs": [
                {"name": "out", "type": "any", "required": True, "description": ""}
            ],
        }
    ]
    line = _format_builtin_reference(registered)
    assert "config: {required_key, optional_key?}" in line
    assert "outputs: out" in line


def test_format_builtin_reference_omits_config_and_io_segments_when_empty():
    """A plugin with no config keys and no inputs/outputs (an edge case, but
    a legal one) renders as just its id -- no dangling 'config: {}' or
    'inputs: '."""
    registered = [
        {
            "id": "civex.bare",
            "builtin": True,
            "config_schema": {"properties": {}, "required": []},
            "inputs": [],
            "outputs": [],
        }
    ]
    assert _format_builtin_reference(registered) == "civex.bare"
