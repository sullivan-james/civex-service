from __future__ import annotations

import io
import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field

from civex.domain.exceptions import ValidationError
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
        delimiter: str = Field(default=",", description="Column separator character.")
        encoding: str = Field(
            default="utf-8", description="Text encoding to decode the CSV bytes with."
        )

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
        try:
            df = pd.read_csv(
                io.BytesIO(raw), sep=config.delimiter, encoding=config.encoding
            )
        except UnicodeDecodeError as e:
            raise ValidationError(
                f"Could not decode CSV bytes as {config.encoding}: {e}"
            ) from e
        except pd.errors.EmptyDataError as e:
            raise ValidationError("CSV file has no data to parse") from e
        except pd.errors.ParserError as e:
            raise ValidationError(f"Could not parse CSV: {e}") from e
        log.info(
            "Parsed CSV: %d rows × %d columns %s",
            len(df),
            len(df.columns),
            list(df.columns),
        )
        return {"table": df}
