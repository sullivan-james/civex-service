from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.rows_to_records"
    name = "Rows to Records"
    description = (
        "Create one new record per table row. Pure insert -- use Upsert "
        "Records to match existing records instead."
    )
    category = "outputs"
    capabilities: list[str] = ["create_record"]
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
        schema_name: str = Field(alias="schema")
        dataset: str = ""  # "" = use ctx.dataset.name
        field_mapping: dict[str, str] = {}  # csv_column → schema_field
        context_record_id: str = ""  # "" = use ctx.get_context_record().id

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.rows_to_records requires pandas: pip install 'civex[workflows]'"
            )

        df = inputs["table"]
        dataset_name = config.dataset or ctx.dataset.name
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
            except ValidationError as e:
                log.warning("  ✗ skipped row %s: %s", data, e)
                skipped += 1

        log.info("Done: %d created, %d skipped", created, skipped)
        return {"created": created, "skipped": skipped}
