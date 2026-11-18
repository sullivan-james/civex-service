from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import hint, says

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    id = "civex.load_file_list"
    name = "Read a list of files"
    description = (
        "Read the file references held in a `file_list` field on the trigger "
        "record. Yields an empty list when the field is unset."
    )
    category = "data-sources"
    capabilities: list[str] = ["read"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(
            name="files",
            type="files",
            description="The files in the field.",
        )
    ]

    class Config(BaseModel):
        model_config = ConfigDict(json_schema_extra=says("Reads the files in {field}."))
        field: str = Field(
            title="Files field",
            json_schema_extra=hint("field", dtypes=["file_list"]),
            description="The file list field of the record it runs on.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        raw = ctx.get_context_record()["data"].get(config.field)
        if not raw:
            log.warning(
                "Field '%s' is empty or missing — no files to process", config.field
            )
            return {"files": []}
        if not isinstance(raw, list):
            raise ValueError(
                f"Field '{config.field}' is not a file_list (got {type(raw).__name__})"
            )
        log.info("Loaded %d file ref(s) from field '%s'", len(raw), config.field)
        return {"files": raw}
