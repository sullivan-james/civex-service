from __future__ import annotations

import re
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field

from civex.domain import filename_extract
from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase


class Plugin(PluginBase):
    id = "civex.extract_from_filename"
    name = "Extract from Filename"
    description = (
        "Apply a regex to a file field's filename and optionally convert the "
        "captured text to a date/datetime/number."
    )
    category = "data-access"
    capabilities: list[str] = ["read"]
    inputs: list[IOSpec] = []
    outputs = [
        IOSpec(
            name="value",
            type="any",
            description="The captured text converted to `output_type`.",
        ),
        IOSpec(
            name="filename",
            type="string",
            description="The filename the pattern was applied to.",
        ),
        IOSpec(
            name="extracted",
            type="string",
            description="The raw captured text, before conversion.",
        ),
    ]

    class Config(BaseModel):
        field: str = Field(
            description="Field on the trigger record holding the filename to match "
            "(a `file`/`file_list` field, or a plain string field)."
        )
        pattern: str = Field(
            default=r"(.+)",
            description="Regex applied to the filename. The first capture group "
            "(or the whole match if there is none) is extracted.",
        )
        output_type: str = Field(
            default="string",
            description="Type to convert the captured text to: "
            "string | integer | float | date | datetime.",
        )
        date_format: str | None = Field(
            default=None,
            description="Token format for parsing the captured text when "
            "`output_type` is date/datetime, e.g. 'YYYYMMDD-HHmmSS'. Tokens are "
            "YYYY MM DD HH mm SS; non-token characters are treated as raw regex, "
            "so e.g. 'YYYYMMDD[-_]HHmmSS' matches both dashes and underscores. "
            "Required when output_type is date or datetime.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        raw_value = ctx.get_context_record()["data"].get(config.field)
        if raw_value is None:
            raise ValueError(f"Field '{config.field}' not found on record")

        if isinstance(raw_value, dict) and "filename" in raw_value:
            filename = raw_value["filename"]
        elif (
            isinstance(raw_value, list) and raw_value and isinstance(raw_value[0], dict)
        ):
            filename = raw_value[0]["filename"]
        elif isinstance(raw_value, str):
            filename = raw_value
        else:
            raise ValueError(
                f"Field '{config.field}' is not a file reference or string"
            )

        m = re.search(config.pattern, filename)
        if m is None:
            raise ValueError(
                f"Pattern '{config.pattern}' did not match filename '{filename}'"
            )
        extracted = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)

        value: Any
        if config.output_type == "integer":
            value = int(extracted)
        elif config.output_type == "float":
            value = float(extracted)
        elif config.output_type in ("date", "datetime"):
            if not config.date_format:
                raise ValueError(
                    "date_format is required when output_type is 'date' or 'datetime'"
                )
            # The parsing is the domain's (`civex.domain.filename_extract`), the
            # same the `from_filename` field rule uses; this plugin only adds
            # the step around it.
            value = filename_extract.parse_by_format(
                extracted, config.date_format, config.output_type
            )
        else:
            value = extracted

        return {"value": value, "filename": filename, "extracted": extracted}
