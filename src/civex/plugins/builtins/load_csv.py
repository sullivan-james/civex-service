from __future__ import annotations

import io
import logging
from typing import Any

from pydantic import BaseModel

from civex.plugins.base import BasePlugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(BasePlugin):
    id = "civex.load_csv"
    name = "Load CSV"
    category = "data-sources"

    class Config(BaseModel):
        delimiter: str = ","
        encoding: str = "utf-8"

    def run(self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("civex.load_csv requires pandas: pip install 'civex[workflows]'")

        raw: bytes = inputs["bytes"]
        df = pd.read_csv(io.BytesIO(raw), sep=config.delimiter, encoding=config.encoding)
        log.info("Parsed CSV: %d rows × %d columns %s", len(df), len(df.columns), list(df.columns))
        return {"table": df}
