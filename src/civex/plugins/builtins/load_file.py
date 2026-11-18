from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.domain.dtos import FileRef
from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import hint, says

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    id = "civex.load_file"
    name = "Read a file"
    description = (
        "Load the bytes of a file stored in a `file` field on the trigger record."
    )
    category = "data-sources"
    capabilities: list[str] = ["read"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(name="bytes", type="bytes", description="The file's contents."),
        IOSpec(name="filename", type="string", description="The file's name."),
        IOSpec(name="sha256", type="string", description="The file's content hash."),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(json_schema_extra=says("Reads the file in {field}."))
        field: str = Field(
            title="File field",
            json_schema_extra=hint("field", dtypes=["file"]),
            description="The file field of the record it runs on.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        raw = ctx.get_context_record()["data"].get(config.field)
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
