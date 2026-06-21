from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from civex.plugins.base import BasePlugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    id = "civex.rows_to_records"
    name = "Rows to Records"
    category = "outputs"

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(alias="schema")
        dataset: str = ""                    # "" = use ctx.dataset.name
        field_mapping: dict[str, str] = {}  # csv_column → schema_field
        parent_record_id: str = ""           # "" = use ctx.record.id

    def run(self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("civex.rows_to_records requires pandas: pip install 'civex[workflows]'")

        df = inputs["table"]
        dataset_name = config.dataset or ctx.dataset.name
        parent_id = config.parent_record_id or str(ctx.record.id)
        log.info("Creating %d records → dataset '%s', schema '%s'", len(df), dataset_name, config.schema_name)
        created = 0
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
            ctx.create_record(dataset_name, config.schema_name, data, parent_record_id=parent_id)
            created += 1

        log.info("Created %d records", created)
        return {"created": created}
