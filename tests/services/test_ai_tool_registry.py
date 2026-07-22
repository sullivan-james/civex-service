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


# ---------------------------------------------------------------------------
# list_schemas -- no prior direct test coverage existed for this tool's
# handler (only indirectly, via the system prompt injecting schema_svc data).
# ---------------------------------------------------------------------------


def test_list_schemas_returns_name_type_and_restrictions(ctx: AppContext) -> None:
    ctx.schema_svc.create("trial", description="t")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.schema_svc.add_field(
        "trial", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()

    result = json.loads(dispatch("list_schemas", {}, _tool_ctx(ctx)))

    assert result == [
        {
            "name": "trial",
            "fields": [
                {"name": "subject", "type": "string"},
                {
                    "name": "age",
                    "type": "integer",
                    "restrictions": {"min": 0, "max": 120},
                },
            ],
        }
    ]


def test_list_schemas_empty_project_returns_empty_list(ctx: AppContext) -> None:
    assert json.loads(dispatch("list_schemas", {}, _tool_ctx(ctx))) == []


# ---------------------------------------------------------------------------
# query_records -- search/count records of one schema across all collections.
# No prior direct test coverage existed for this tool's handler.
# ---------------------------------------------------------------------------


def _seed_query_records(ctx: AppContext) -> None:
    ctx.schema_svc.create("trial", description="t")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.dataset_svc.create("study")
    for sub in ["S01", "S02", "S03"]:
        ctx.record_svc.add("study", "trial", {"subject": sub})
    ctx.commit()


def test_query_records_returns_total_and_records(ctx: AppContext) -> None:
    _seed_query_records(ctx)
    result = json.loads(dispatch("query_records", {"schema": "trial"}, _tool_ctx(ctx)))
    assert result["total"] == "3"
    assert len(result["records"]) == 3
    assert all("id" in r and "data" in r for r in result["records"])


def test_query_records_count_only_omits_records(ctx: AppContext) -> None:
    _seed_query_records(ctx)
    result = json.loads(
        dispatch(
            "query_records", {"schema": "trial", "count_only": True}, _tool_ctx(ctx)
        )
    )
    assert result == {"total": "3"}


def test_query_records_search_filters_results(ctx: AppContext) -> None:
    _seed_query_records(ctx)
    result = json.loads(
        dispatch(
            "query_records", {"schema": "trial", "search": "S02"}, _tool_ctx(ctx)
        )
    )
    assert result["total"] == "1"
    assert result["records"][0]["data"]["subject"] == "S02"


def test_query_records_limit_bounds_returned_records_not_total(
    ctx: AppContext,
) -> None:
    _seed_query_records(ctx)
    result = json.loads(
        dispatch("query_records", {"schema": "trial", "limit": 1}, _tool_ctx(ctx))
    )
    assert result["total"] == "3"  # true total still reported
    assert len(result["records"]) == 1  # but payload is bounded


def test_query_records_unknown_schema_returns_error(ctx: AppContext) -> None:
    result = json.loads(dispatch("query_records", {"schema": "ghost"}, _tool_ctx(ctx)))
    assert "error" in result
    assert "ghost" in result["error"]


def test_list_workflows_tool_reads_via_workflow_service(ctx: AppContext) -> None:
    ctx.workflow_svc.save("my-wf", "name: my-wf\nsteps: []\n")
    result = json.loads(dispatch("list_workflows", {}, _tool_ctx(ctx)))
    assert result == [{"filename": "my-wf.yaml", "content": "name: my-wf\nsteps: []\n"}]


def test_list_plugins_tool_reads_via_plugin_service(ctx: AppContext) -> None:
    """list_plugins returns both structured metadata for every registered
    plugin (built-ins + custom, incl. category/config_schema -- CIVEX-56)
    and full source for custom plugin files."""
    code = (
        "# /// script\n"
        '# requires-python = ">=3.10"\n'
        '# dependencies = ["civex-plugin-sdk"]\n'
        "# ///\n"
        "from pydantic import BaseModel\n"
        "from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve\n\n"
        "class Plugin(PluginBase):\n"
        '    id = "project.demo"\n'
        '    name = "Demo"\n\n'
        "    class Config(BaseModel):\n"
        "        pass\n\n"
        "    def invoke(self, inputs, config, ctx: Ctx) -> dict:\n"
        "        return {}\n\n"
        'if __name__ == "__main__":\n'
        "    serve(Plugin)\n"
    )
    ctx.plugin_svc.save("demo", code)
    result = json.loads(dispatch("list_plugins", {}, _tool_ctx(ctx)))

    assert result["custom_source"] == [{"filename": "demo.py", "code": code}]

    registered = {p["id"]: p for p in result["registered"]}
    assert registered["project.demo"]["builtin"] is False
    assert registered["project.demo"]["category"] == "general"
    assert registered["project.demo"]["config_schema"] == {
        "title": "Config",
        "type": "object",
        "properties": {},
    }
    assert any(pid.startswith("civex.") for pid in registered)
    builtin = next(p for pid, p in registered.items() if pid.startswith("civex."))
    assert builtin["builtin"] is True
    assert isinstance(builtin["category"], str) and builtin["category"]
    assert "properties" in builtin["config_schema"]


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
        dispatch(
            "save_workflow", {"stem": "my-wf", "content": "not: [valid"}, _tool_ctx(ctx)
        )
    )
    assert result["status"] == "error"
    assert "Invalid workflow YAML" in result["message"]


def test_save_plugin_tool_validates_without_writing(ctx: AppContext) -> None:
    code = (
        "from pydantic import BaseModel\n"
        "from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve\n\n"
        "class Plugin(PluginBase):\n"
        '    id = "project.demo"\n'
        '    name = "Demo"\n\n'
        "    class Config(BaseModel):\n"
        "        pass\n\n"
        "    def invoke(self, inputs, config, ctx: Ctx) -> dict:\n"
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
