from __future__ import annotations

from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import hint, says


class Plugin(PluginBase):
    id = "civex.save_field"
    name = "Set a field"
    description = "Write a value to a single field on the trigger record."
    category = "outputs"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [IOSpec(name="value", type="any", description="The value to write.")]
    outputs: list[IOSpec] = []

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says("Sets this record's {field} to {value}.")
        )
        field: str = Field(
            title="Field to set",
            json_schema_extra=hint("field"),
            description="The field of the record it runs on to set.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        # Only this field changes; the others are read as they are now, not as
        # they were when the workflow started.
        record_id = ctx.get_context_record()["id"]
        ctx.patch_record(record_id, {config.field: inputs["value"]})
        return {}
