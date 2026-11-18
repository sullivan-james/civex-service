from __future__ import annotations

from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import hint, says


class Plugin(PluginBase):
    id = "civex.get_field"
    name = "Read a field"
    description = "Read a single field from the record that triggered the workflow."
    category = "data-access"
    capabilities: list[str] = ["read"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(
            name="value",
            type="any",
            description="The field's value; empty when it isn't set.",
        )
    ]

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says("Reads this record's {field}.")
        )
        field: str = Field(
            title="Field",
            json_schema_extra=hint("field"),
            description="The field of the record it runs on to read.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        value = ctx.get_context_record()["data"].get(config.field)
        return {"value": value}
