from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import NotFoundError, ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.upsert_records"
    name = "Upsert Records"
    description = (
        "Create or update one record per table row, matching existing records "
        "on a key column."
    )
    category = "outputs"
    capabilities: list[str] = ["create_record", "update_record", "find_records"]
    inputs = [
        IOSpec(
            name="table",
            type="table",
            description="Rows to upsert; columns map to schema fields by name.",
        )
    ]
    outputs = [
        IOSpec(name="created", type="number", description="Rows that inserted."),
        IOSpec(name="updated", type="number", description="Rows that matched."),
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
            description="Name of the schema to create/update records under. "
            "Workflow YAML sets this via the `schema:` key (the Python field is "
            "`schema_name`).",
        )
        key_field: str = Field(
            description="Field used to match table rows against existing records."
        )
        dataset: str = Field(
            default="",
            description="Dataset to search and create records in. Empty string "
            "falls back to the trigger record's own dataset.",
        )
        parent_record_id: str = Field(
            default="",
            description="Parent record ID to scope matching and creation to. "
            "Empty string falls back to the trigger record's ID.",
        )

    def invoke(
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

        log.info(
            "Upserting %d rows → dataset '%s', schema '%s', key '%s'",
            len(df),
            dataset_name,
            config.schema_name,
            config.key_field,
        )
        created = updated = skipped = 0

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

            existing = ctx.find_records(
                dataset_name,
                schema_name=config.schema_name,
                parent_record_id=parent_id,
                filters=[f"{config.key_field}={key_value}"],
                limit=1,
            )

            try:
                if existing:
                    ctx.update_record(str(existing[0].id), data)
                    updated += 1
                else:
                    ctx.create_record(
                        dataset_name,
                        config.schema_name,
                        data,
                        context_record_id=parent_id,
                    )
                    created += 1
            except (ValidationError, NotFoundError) as e:
                # NotFoundError alongside ValidationError: the matched record
                # can be deleted between find_records() above and this
                # update() (e.g. another workflow step, or a concurrent
                # delete) -- that race should skip the row like any other
                # per-row failure, not abort the whole upsert.
                log.warning("  ✗ skipped row %s: %s", data, e)
                skipped += 1

        log.info(
            "Upsert done: %d created, %d updated, %d skipped", created, updated, skipped
        )
        return {"created": created, "updated": updated, "skipped": skipped}
