from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from civex.plugins.base import BasePlugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    id = "civex.load_file_list"
    name = "Load File List"
    category = "data-sources"

    class Config(BaseModel):
        field: str  # name of the file_list field on the trigger record

    def run(self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext) -> dict[str, Any]:
        raw = ctx.record.data.get(config.field)
        if not raw:
            log.warning("Field '%s' is empty or missing — no files to process", config.field)
            return {"files": []}
        if not isinstance(raw, list):
            raise ValueError(f"Field '{config.field}' is not a file_list (got {type(raw).__name__})")
        log.info("Loaded %d file ref(s) from field '%s'", len(raw), config.field)
        return {"files": raw}
