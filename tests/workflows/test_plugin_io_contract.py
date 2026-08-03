"""Every plugin tier is held to one contract: a step's outputs must always
be JSON-serializable, so a workflow behaves identically regardless of which
tier a step happens to run on. `table`/`bytes`-typed IOSpec values get
transparent DataFrame/bytes <-> columnar-typed-envelope/binary-envelope
conversion at the plugin invocation boundary (civex_plugin_sdk.io_convert,
wired into both registry._registration_for_tier0 and
civex_plugin_sdk.serve._handle_run); anything else non-serializable that
slips through is caught by a strict `json.dumps` check in executor.run() and
raised as PluginContractError.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from civex.domain.exceptions import PluginContractError
from civex.plugins.base import PluginTier, StepResult, WorkflowContext
from civex.plugins.registry import (
    PluginRegistration,
    all_plugins,
    discover_user_plugins,
)
from civex.workflows import executor
from civex.workflows.definition import WorkflowDef


def test_table_data_crosses_a_builtin_to_builtin_chain_as_records_not_a_dataframe(
    ctx, make_collection, make_schema, make_record
):
    """civex.load_csv -> civex.rows_to_records, both BUILTIN-tier -- proves
    the dataflow between two in-process steps is genuinely list[dict]
    records, the same shape a subprocess/container-tier step downstream
    would receive, rather than a raw DataFrame that only happens to work
    in-process."""
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema("item", fields=[("name", "string"), ("age", "integer")])
    wf_ctx = WorkflowContext(record=trigger, dataset=dataset, _app_ctx=ctx)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: csv-to-records
inputs:
  bytes: {type: bytes}
steps:
  - id: parse
    plugin: civex.load_csv
    inputs: {bytes: __input__.bytes}
  - id: create
    plugin: civex.rows_to_records
    config: {schema: item}
    inputs: {table: parse.table}
""")
    )

    csv_bytes = b"name,age\nAlice,30\nBob,25\n"
    step_executions = executor.run(
        wf, wf_ctx, all_plugins(), initial_outputs={"__input__": {"bytes": csv_bytes}}
    )

    parse_outputs = step_executions[0]["outputs"]
    # A raw DataFrame would persist as executor._json_safe's summary dict
    # ({"rows": ..., "columns": [...]}), never as this columnar/typed
    # envelope -- so this also proves the *actual* step_outputs value
    # threaded into "create" was already the wire form, not just that
    # display serialization tolerated it. "create" (civex.rows_to_records)
    # still reconstructs a real DataFrame from this and calls df.iterrows()
    # -- proven by the record-creation assertion below succeeding at all.
    assert parse_outputs["table"] == {
        "encoding": "inline",
        "columns": ["name", "age"],
        "dtypes": {"name": "string", "age": "integer"},
        "data": {"name": ["Alice", "Bob"], "age": [30, 25]},
    }

    created = ctx.record_svc.find("study", schema_name="item")
    assert {r.data["name"] for r in created} == {"Alice", "Bob"}


_TABLE_PLUGIN_CODE = """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk[table]"]
# ///
from typing import Any

from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve
from civex_plugin_sdk.plugin_base import IOSpec

class Plugin(PluginBase):
    id = "project.rename_columns"
    name = "Rename Columns"
    capabilities = []
    inputs = [IOSpec(name="table", type="table")]
    outputs = [IOSpec(name="table", type="table")]

    class Config(BaseModel):
        pass

    def invoke(self, inputs: dict[str, Any], config: Config, ctx: Ctx) -> dict:
        table = inputs["table"]
        # A DataFrame method, not a dict/list one -- this is what proves the
        # host handed the step a reconstructed table rather than the raw
        # envelope, and it fails loudly rather than silently if it didn't.
        table = table.rename(columns={"name": "label"})
        table["seen"] = True
        return {"table": table}

if __name__ == "__main__":
    serve(Plugin)
"""


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed on PATH")
def test_a_table_crosses_from_a_builtin_step_into_a_real_subprocess_step(
    ctx, make_collection, make_schema, make_record, tmp_path: Path
):
    """Regression: civex.load_csv (BUILTIN) -> a real Tier 1 `uv run`
    plugin -> civex.upsert_records (BUILTIN).

    The crossing is the whole point. A BUILTIN step's raw pandas DataFrame
    used to be threaded straight into the subprocess step's RunRequest, where
    json.dumps raised `Object of type DataFrame is not JSON serializable` --
    a failure that could only ever show up at a tier boundary, which is
    exactly what the builtin-to-builtin test above cannot catch.
    """
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema("item", fields=[("label", "string"), ("age", "integer")])
    wf_ctx = WorkflowContext(record=trigger, dataset=dataset, _app_ctx=ctx)

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "rename_columns.py").write_text(_TABLE_PLUGIN_CODE)
    discover_user_plugins(plugins_dir)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: csv-through-a-subprocess
inputs:
  bytes: {type: bytes}
steps:
  - id: parse
    plugin: civex.load_csv
    inputs: {bytes: __input__.bytes}
  - id: rename
    plugin: project.rename_columns
    inputs: {table: parse.table}
  - id: upsert
    plugin: civex.upsert_records
    config: {schema: item, key_field: label}
    inputs: {table: rename.table}
""")
    )

    csv_bytes = b"name,age\nAlice,30\nBob,25\n"
    step_executions = executor.run(
        wf,
        wf_ctx,
        all_plugins(),
        initial_outputs={"__input__": {"bytes": csv_bytes}},
        default_timeout_seconds=120.0,
    )

    assert [s["status"] for s in step_executions] == ["success"] * 3
    assert step_executions[2]["outputs"] == {"created": 2, "updated": 0, "skipped": 0}

    created = ctx.record_svc.find("study", schema_name="item")
    assert {r.data["label"] for r in created} == {"Alice", "Bob"}
    assert {r.data["age"] for r in created} == {30, 25}


class _BadConfig(BaseModel):
    pass


def _bad_invoke(inputs, config, ctx, timeout):
    return StepResult(outputs={"bad": {1, 2, 3}})  # a set: not JSON-serializable


def test_a_non_serializable_output_raises_a_plugin_contract_error(
    ctx, make_collection, make_schema, make_record
):
    """Not every non-serializable shape is covered by the table/bytes sugar
    layer -- this is the backstop that keeps BUILTIN-tier steps from
    silently getting away with returning something a subprocess/
    container-tier plugin never could."""
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    wf_ctx = WorkflowContext(record=trigger, dataset=dataset, _app_ctx=ctx)

    bad_plugin = PluginRegistration(
        id="test.bad",
        name="Bad",
        category="test",
        tier=PluginTier.BUILTIN,
        capabilities=[],
        description="",
        inputs=None,
        outputs=None,
        config_model=_BadConfig,
        module_name=__name__,
        invoke=_bad_invoke,
    )

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: bad
steps:
  - id: step1
    plugin: test.bad
""")
    )

    try:
        executor.run(wf, wf_ctx, {"test.bad": bad_plugin})
        assert False, "expected a PluginContractError"
    except PluginContractError as e:
        assert e.kind == "plugin_contract_error"
        assert "step1" in str(e)
        assert e.step_executions[0]["step_id"] == "step1"  # type: ignore[attr-defined]
        assert e.step_executions[0]["status"] == "failed"  # type: ignore[attr-defined]
