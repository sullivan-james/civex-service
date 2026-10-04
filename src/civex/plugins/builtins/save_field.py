from __future__ import annotations

from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field

from civex.plugins.base import Tier0Plugin, WorkflowContext


class Plugin(Tier0Plugin):
    id = "civex.save_field"
    name = "Save Field"
    description = "Write a value to a single field on the trigger record."
    category = "outputs"
    capabilities: list[str] = ["update_record"]
    inputs = [IOSpec(name="value", type="any", description="The value to write.")]
    outputs: list[IOSpec] = []

    class Config(BaseModel):
        field: str = Field(
            description="Name of the field on the trigger record to write to."
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        # Only this field changes; the others are read as they are now, not as
        # they were when the workflow started.
        ctx.patch_record(str(ctx.record.id), {config.field: inputs["value"]})
        return {}
