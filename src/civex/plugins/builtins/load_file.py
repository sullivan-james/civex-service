from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from civex.domain.dtos import FileRef
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.load_file"
    name = "Load File"
    category = "data-sources"
    capabilities: list[str] = ["get_file"]

    class Config(BaseModel):
        field: str  # field name on the trigger record containing a FileRef

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        raw = ctx.record.data.get(config.field)
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
