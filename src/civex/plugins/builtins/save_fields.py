from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel

from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.save_fields"
    name = "Save Fields"
    description = (
        "Write several fields to the trigger record at once. Updates with a "
        "null value are skipped rather than clearing the field."
    )
    category = "outputs"
    capabilities: list[str] = ["update_record"]
    inputs = [
        IOSpec(
            name="updates",
            type="mapping",
            description="field name → value. Null values are ignored.",
        )
    ]
    outputs: list[IOSpec] = []

    class Config(BaseModel):
        pass

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        updates: dict[str, Any] = inputs["updates"]
        # Null values are skipped, and the record's other fields are read as they
        # are now, not as they were when the workflow started.
        changes = {k: v for k, v in updates.items() if v is not None}
        log.info(
            "Saving %d field(s) to record %s: %s",
            len(updates),
            str(ctx.record.id)[:8],
            list(updates.keys()),
        )
        ctx.patch_record(str(ctx.record.id), changes)
        return {}
