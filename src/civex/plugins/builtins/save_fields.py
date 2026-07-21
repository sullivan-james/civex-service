from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.save_fields"
    name = "Save Fields"
    category = "outputs"
    capabilities: list[str] = ["update_record"]

    class Config(BaseModel):
        pass

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        updates: dict[str, Any] = inputs["updates"]
        data = dict(ctx.record.data)
        data.update({k: v for k, v in updates.items() if v is not None})
        log.info(
            "Saving %d field(s) to record %s: %s",
            len(updates),
            str(ctx.record.id)[:8],
            list(updates.keys()),
        )
        ctx.update_record(data)
        return {}
