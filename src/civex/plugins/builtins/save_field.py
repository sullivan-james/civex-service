from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from civex.plugins.base import BasePlugin, WorkflowContext


class Plugin(BasePlugin):
    id = "civex.save_field"
    name = "Save Field"
    category = "outputs"

    class Config(BaseModel):
        field: str  # field name on the trigger record to write to

    def run(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        value = inputs["value"]
        updated = dict(ctx.record.data)
        updated[config.field] = value
        ctx.update_record(updated)
        return {}
