from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from civex.plugins.base import BasePlugin, WorkflowContext


class Plugin(BasePlugin):
    id = "civex.get_field"
    name = "Get Field"
    category = "data-access"

    class Config(BaseModel):
        field: str

    def run(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        value = ctx.record.data.get(config.field)
        return {"value": value}
