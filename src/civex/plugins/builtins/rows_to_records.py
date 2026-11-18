from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex_plugin_sdk import RpcError

from civex.plugins.builtins._refusals import refused
from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    id = "civex.rows_to_records"
    name = "Rows to Records"
    description = (
        "Create one new record per table row. Pure insert -- use Upsert "
        "Records to match existing records instead."
    )
    category = "outputs"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="table",
            type="table",
            description="Rows to insert; columns map to schema fields by name unless `field_mapping` is set.",
        )
    ]
    outputs = [
        IOSpec(name="created", type="number", description="Records created."),
        IOSpec(
            name="skipped",
            type="number",
            description="Rows whose record failed validation.",
        ),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(
            alias="schema",
            description="Name of the schema to create records under. Workflow "
            "YAML sets this via the `schema:` key (the Python field is "
            "`schema_name`).",
        )
        dataset: str = Field(
            default="",
            description="Dataset to create records in. Empty string falls back "
            "to the trigger record's own dataset.",
        )
        field_mapping: dict[str, str] = Field(
            default_factory=dict,
            description="Maps table column names to schema field names. Empty "
            "means columns are used as schema field names directly.",
        )
        context_record_id: str = Field(
            default="",
            description="Parent record ID to attach created records to. Empty "
            "string falls back to the workflow's context record.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.rows_to_records requires pandas: pip install 'civex[workflows]'"
            )

        df = inputs["table"]
        dataset_name = config.dataset or ctx.get_context_dataset()["name"]
        log.info(
            "Creating %d records → dataset '%s', schema '%s'",
            len(df),
            dataset_name,
            config.schema_name,
        )
        created = skipped = 0
        for _, row in df.iterrows():
            if config.field_mapping:
                raw = {
                    schema_field: row[csv_col]
                    for csv_col, schema_field in config.field_mapping.items()
                    if csv_col in row
                }
            else:
                raw = {col: row[col] for col in df.columns}
            data = {
                k: (v.item() if hasattr(v, "item") else v)
                for k, v in raw.items()
                if not pd.isna(v)
            }
            try:
                ctx.create_record(
                    dataset_name,
                    config.schema_name,
                    data,
                    context_record_id=config.context_record_id or None,
                )
                created += 1
            except RpcError as e:
                if not refused(e):
                    raise
                log.warning("  ✗ skipped row %s: %s", data, e)
                skipped += 1

        log.info("Done: %d created, %d skipped", created, skipped)
        return {"created": created, "skipped": skipped}
