from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from civex.plugins.base import Tier0Plugin, WorkflowContext


class Plugin(Tier0Plugin):
    id = "civex.get_field"
    name = "Get Field"
    category = "data-access"
    capabilities: list[str] = []

    class Config(BaseModel):
        field: str

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        value = ctx.record.data.get(config.field)
        return {"value": value}
