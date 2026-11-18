from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex_plugin_sdk import RpcError

from civex.plugins.builtins._refusals import refused
from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import advanced, hint, says

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    id = "civex.create_records_from_files"
    name = "Make a record for each file"
    description = (
        "Create one record per file in a list. Pure insert -- no key matching "
        "against existing records; use Match Files to Records for that."
    )
    category = "outputs"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="files",
            type="files",
            description="The files to make records from, one record each.",
        )
    ]
    outputs = [
        IOSpec(name="created", type="number", description="How many records it made."),
        IOSpec(
            name="skipped",
            type="number",
            description="The files whose record could not be made.",
        ),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "Makes a {schema} inside this record for each of {files}, with the file in its {file_field}."
            ),
            populate_by_name=True,
        )
        schema_name: str = Field(
            title="Kind of record to make",
            json_schema_extra=hint("schema"),
            alias="schema",
            description="Name of the schema to create records under. Workflow "
            "YAML sets this via the `schema:` key (the Python field is "
            "`schema_name`).",
        )
        file_field: str = Field(
            title="Put the file in field",
            json_schema_extra=hint("field", of="schema", dtypes=["file", "file_list"]),
            description="The file field of each new record.",
        )
        dataset: str = Field(
            title="Collection",
            json_schema_extra=advanced(hint("collection")),
            default="",
            description="Dataset to create records in. Empty string falls back "
            "to the trigger record's own dataset.",
        )
        context_record_id: str = Field(
            title="Inside record",
            json_schema_extra=advanced(hint("record")),
            default="",
            description="Parent record ID to attach created records to. Empty "
            "string falls back to the workflow's context record.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        files: list[dict[str, Any]] = inputs["files"]
        dataset_name = config.dataset or ctx.get_context_dataset()["name"]

        log.info(
            "Creating %d %s record(s) in dataset '%s'",
            len(files),
            config.schema_name,
            dataset_name,
        )

        created = skipped = 0
        for ref in files:
            try:
                ctx.create_record(
                    dataset_name,
                    config.schema_name,
                    {config.file_field: ref},
                    context_record_id=config.context_record_id or None,
                )
                log.info(
                    "  ✓ created %s from '%s'",
                    config.schema_name,
                    ref.get("filename", "?"),
                )
                created += 1
            except RpcError as e:
                if not refused(e):
                    raise
                log.warning("  ✗ skipped '%s': %s", ref.get("filename", "?"), e)
                skipped += 1

        log.info("Done: %d created, %d skipped", created, skipped)
        return {"created": created, "skipped": skipped}
