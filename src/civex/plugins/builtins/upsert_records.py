from __future__ import annotations

from typing import Any

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.plugins.builtins._table_rows import save_rows
from civex.plugins.builtins.rows_to_records import OUTPUTS
from civex.plugins.hints import advanced, hint, says


class Plugin(PluginBase):
    """The older name of `civex.rows_to_records` with one key field: kept so
    workflows saved with it run as they did; the work is the same code."""

    id = "civex.upsert_records"
    name = "Add or update records from a table"
    description = (
        "The older name of Make a record for each row, matching on one field. "
        "Create or update one record per table row, matching existing records "
        "on a key column. An update changes only the columns in the table; the "
        "record's other fields are kept, and an empty cell never clears a value."
    )
    category = "outputs"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="table",
            type="table",
            description="The table to save. Its columns go into the fields of the same name.",
        )
    ]
    outputs = OUTPUTS

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "For each row of {table}, updates the {schema} inside this record whose {key_field} matches it, or makes a new one."
            ),
            populate_by_name=True,
        )
        schema_name: str = Field(
            title="Kind of record",
            json_schema_extra=hint("schema"),
            alias="schema",
            description="Name of the schema to create/update records under. "
            "Workflow YAML sets this via the `schema:` key (the Python field is "
            "`schema_name`).",
        )
        key_field: str = Field(
            title="Match rows by field",
            json_schema_extra=hint("field", of="schema"),
            description="The field a row and a record must agree on to be the same.",
        )
        dataset: str = Field(
            title="Collection",
            json_schema_extra=advanced(hint("collection")),
            default="",
            description="Dataset to search and create records in. Empty string "
            "falls back to the trigger record's own dataset.",
        )
        parent_record_id: str = Field(
            title="Inside record",
            json_schema_extra=advanced(hint("record")),
            default="",
            description="Parent record ID to scope matching and creation to. "
            "Empty string falls back to the trigger record's ID.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        return save_rows(
            ctx,
            inputs["table"],
            schema_name=config.schema_name,
            dataset=config.dataset,
            match_on=[config.key_field],
            mapping={},
            parent_record_id=config.parent_record_id,
        )
