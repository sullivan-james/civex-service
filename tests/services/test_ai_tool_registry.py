"""services/ai/tools/registry.py: registration, dispatch, and the
str-vs-dict passthrough contract (CIVEX-54). No prior test coverage existed
for the registry itself (only for individual tool behaviors, in
tests/test_ai_act_tools.py) -- these are new tests, not characterization.
"""

from __future__ import annotations

import json

from civex.context import AppContext
from civex.services.ai.tools.base import AiToolContext
from civex.services.ai.tools.registry import TOOL_REGISTRY, all_tools, dispatch


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


def test_all_tools_have_unique_non_empty_names() -> None:
    names = [cls.name for cls in TOOL_REGISTRY.values()]
    assert len(names) == len(set(names))
    assert all(names)


def test_all_tools_declare_a_description_and_input_schema() -> None:
    for cls in TOOL_REGISTRY.values():
        assert cls.description
        assert isinstance(cls.input_schema, dict)


def test_all_tools_covers_the_22_expected_tools() -> None:
    assert set(all_tools()) == {
        "list_schemas",
        "list_collections",
        "query_records",
        "list_records",
        "get_job_log",
        "list_workflows",
        "list_plugins",
        "get_workflow_authoring_guide",
        "save_workflow",
        "save_plugin",
        "create_record",
        "update_record",
        "delete_record",
        "create_schema",
        "update_schema",
        "delete_schema",
        "add_schema_field",
        "update_schema_field",
        "delete_schema_field",
        "create_collection",
        "update_collection",
        "delete_collection",
    }


def test_dispatch_unknown_tool_returns_error(ctx: AppContext) -> None:
    result = json.loads(dispatch("not_a_real_tool", {}, _tool_ctx(ctx)))
    assert result == {"error": "unknown tool: not_a_real_tool"}


def test_dispatch_read_tool_returns_json_encoded_dict(ctx: AppContext) -> None:
    result_str = dispatch("list_collections", {}, _tool_ctx(ctx))
    assert json.loads(result_str) == []


def test_dispatch_get_workflow_authoring_guide_passes_raw_markdown_through(
    ctx: AppContext,
) -> None:
    """This tool returns markdown, not JSON -- dispatch() must not
    json.dumps() it (that would wrap it in quotes and escape newlines)."""
    result = dispatch("get_workflow_authoring_guide", {}, _tool_ctx(ctx))
    assert result.startswith("## Workflow YAML format")
    assert "\\n" not in result  # not JSON-escaped
    assert not result.startswith('"')  # not a JSON string literal either


def test_dispatch_exception_in_tool_run_is_caught(ctx: AppContext, monkeypatch) -> None:
    from civex.services.ai.tools.builtins.read_tools import ListCollectionsTool

    def _boom(self, tool_input, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(ListCollectionsTool, "run", _boom)
    result = json.loads(dispatch("list_collections", {}, _tool_ctx(ctx)))
    assert result == {"error": "kaboom"}


def test_list_workflows_tool_reads_via_workflow_service(ctx: AppContext) -> None:
    ctx.workflow_svc.save("my-wf", "name: my-wf\nsteps: []\n")
    result = json.loads(dispatch("list_workflows", {}, _tool_ctx(ctx)))
    assert result == [{"filename": "my-wf.yaml", "content": "name: my-wf\nsteps: []\n"}]


def test_list_plugins_tool_reads_via_plugin_service(ctx: AppContext) -> None:
    code = (
        "from civex.plugins.base import BasePlugin, WorkflowContext\n\n"
        "class Plugin(BasePlugin):\n"
        '    id = "project.demo"\n'
        '    name = "Demo"\n\n'
        "    def run(self, inputs, config, ctx: WorkflowContext) -> dict:\n"
        "        return {}\n"
    )
    ctx.plugin_svc.save("demo", code)
    result = json.loads(dispatch("list_plugins", {}, _tool_ctx(ctx)))
    assert result == [{"filename": "demo.py", "code": code}]


def test_save_workflow_tool_validates_without_writing(ctx: AppContext) -> None:
    result = json.loads(
        dispatch(
            "save_workflow",
            {"stem": "my-wf", "content": "name: my-wf\nsteps: []\n"},
            _tool_ctx(ctx),
        )
    )
    assert result["status"] == "proposed"
    assert ctx.workflow_svc.list_defs() == []  # nothing written to disk


def test_save_workflow_tool_rejects_invalid_yaml(ctx: AppContext) -> None:
    result = json.loads(
        dispatch("save_workflow", {"stem": "my-wf", "content": "not: [valid"}, _tool_ctx(ctx))
    )
    assert result["status"] == "error"
    assert "Invalid workflow YAML" in result["message"]


def test_save_plugin_tool_validates_without_writing(ctx: AppContext) -> None:
    code = (
        "from civex.plugins.base import BasePlugin, WorkflowContext\n\n"
        "class Plugin(BasePlugin):\n"
        '    id = "project.demo"\n'
        '    name = "Demo"\n\n'
        "    def run(self, inputs, config, ctx: WorkflowContext) -> dict:\n"
        "        return {}\n"
    )
    result = json.loads(
        dispatch("save_plugin", {"name": "demo", "code": code}, _tool_ctx(ctx))
    )
    assert result["status"] == "proposed"
    assert ctx.plugin_svc.list_raw() == []  # nothing written to disk


def test_save_plugin_tool_rejects_missing_plugin_class(ctx: AppContext) -> None:
    result = json.loads(
        dispatch("save_plugin", {"name": "demo", "code": "x = 1"}, _tool_ctx(ctx))
    )
    assert result["status"] == "error"
    assert "class named 'Plugin'" in result["message"]
