from __future__ import annotations

import io
import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel

from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.load_csv"
    name = "Load CSV"
    description = "Parse CSV bytes into a table for a downstream records step."
    category = "data-sources"
    capabilities: list[str] = []
    inputs = [IOSpec(name="bytes", type="bytes", description="Raw CSV file contents.")]
    outputs = [
        IOSpec(name="table", type="table", description="The parsed rows and columns.")
    ]

    class Config(BaseModel):
        delimiter: str = ","
        encoding: str = "utf-8"

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.load_csv requires pandas: pip install 'civex[workflows]'"
            )

        raw: bytes = inputs["bytes"]
        df = pd.read_csv(
            io.BytesIO(raw), sep=config.delimiter, encoding=config.encoding
        )
        log.info(
            "Parsed CSV: %d rows × %d columns %s",
            len(df),
            len(df.columns),
            list(df.columns),
        )
        return {"table": df}
