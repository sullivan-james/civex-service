from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field

from civex.domain.dtos import FileRef
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.load_file"
    name = "Load File"
    description = (
        "Load the bytes of a file stored in a `file` field on the trigger record."
    )
    category = "data-sources"
    capabilities: list[str] = ["get_file"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(name="bytes", type="bytes", description="The file's raw contents."),
        IOSpec(name="filename", type="string", description="Original filename."),
        IOSpec(name="sha256", type="string", description="Content hash of the file."),
    ]

    class Config(BaseModel):
        field: str = Field(
            description="Name of the `file` field on the trigger record to load."
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        raw = ctx.record.data.get(config.field)
        if raw is None:
            raise ValueError(f"Field '{config.field}' not found on record")
        if not isinstance(raw, dict) or "sha256" not in raw:
            raise ValueError(f"Field '{config.field}' is not a file reference")
        ref = FileRef.from_dict(raw)
        data = ctx.get_file(ref.sha256)
        log.info(
            "Loaded '%s' from field '%s' (%d bytes)",
            ref.filename,
            config.field,
            len(data),
        )
        return {"bytes": data, "filename": ref.filename, "sha256": ref.sha256}
