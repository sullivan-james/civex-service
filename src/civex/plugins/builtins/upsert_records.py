from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from civex.plugins.base import BasePlugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    id = "civex.upsert_records"
    name = "Upsert Records"
    category = "outputs"

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(alias="schema")
        key_field: str  # field used to match existing records
        dataset: str = ""  # defaults to ctx.dataset.name
        parent_record_id: str = ""  # defaults to ctx.record.id

    def run(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.upsert_records requires pandas: pip install 'civex[workflows]'"
            )

        df: pd.DataFrame = inputs["table"]
        dataset_name = config.dataset or ctx.dataset.name
        parent_id = config.parent_record_id or str(ctx.record.id)
        record_svc = ctx._app_ctx.record_svc

        log.info(
            "Upserting %d rows → dataset '%s', schema '%s', key '%s'",
            len(df),
            dataset_name,
            config.schema_name,
            config.key_field,
        )
        created = updated = 0

        for _, row in df.iterrows():
            data: dict[str, Any] = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    continue
                data[col] = val.item() if hasattr(val, "item") else val

            key_value = data.get(config.key_field)
            if key_value is None:
                continue

            existing = record_svc.find(
                dataset_name,
                schema_name=config.schema_name,
                parent_record_id=parent_id,
                filters=[f"{config.key_field}={key_value}"],
                limit=1,
            )

            if existing:
                record_svc.update(str(existing[0].id), data)
                updated += 1
            else:
                record_svc.add(
                    dataset_name, config.schema_name, data, parent_record_id=parent_id
                )
                created += 1

        log.info("Upsert done: %d created, %d updated", created, updated)
        return {"created": created, "updated": updated}
