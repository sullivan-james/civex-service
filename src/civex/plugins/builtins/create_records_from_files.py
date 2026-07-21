from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.create_records_from_files"
    name = "Create Records from Files"
    category = "outputs"
    capabilities: list[str] = ["create_record"]

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(alias="schema")
        file_field: str
        dataset: str = ""
        parent_record_id: str = ""

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        files: list[dict[str, Any]] = inputs["files"]
        dataset_name = config.dataset or ctx.dataset.name
        parent_id = config.parent_record_id or str(ctx.record.id)

        log.info(
            "Creating %d %s record(s) in dataset '%s'",
            len(files),
            config.schema_name,
            dataset_name,
        )

        created = skipped = 0
        for ref in files:
            try:
                ctx._app_ctx.record_svc.add(
                    dataset_name,
                    config.schema_name,
                    {config.file_field: ref},
                    parent_record_id=parent_id,
                )
                log.info(
                    "  ✓ created %s from '%s'",
                    config.schema_name,
                    ref.get("filename", "?"),
                )
                created += 1
            except ValidationError as e:
                log.warning("  ✗ skipped '%s': %s", ref.get("filename", "?"), e)
                skipped += 1

        log.info("Done: %d created, %d skipped", created, skipped)
        return {"created": created, "skipped": skipped}
