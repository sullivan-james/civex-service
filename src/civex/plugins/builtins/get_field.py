from __future__ import annotations

from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase


class Plugin(PluginBase):
    id = "civex.get_field"
    name = "Get Field"
    description = "Read a single field from the record that triggered the workflow."
    category = "data-access"
    capabilities: list[str] = ["read"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(
            name="value",
            type="any",
            description="The field's current value, or null if unset.",
        )
    ]

    class Config(BaseModel):
        field: str = Field(
            description="Name of the field to read from the trigger record."
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        value = ctx.get_context_record()["data"].get(config.field)
        return {"value": value}
