from __future__ import annotations

from typing import Any

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.plugins.builtins._table_rows import save_rows
from civex.plugins.hints import advanced, hint, says

#: What both names of this step give back (`civex.upsert_records` too).
OUTPUTS = [
    IOSpec(name="created", type="number", description="How many records it made."),
    IOSpec(
        name="updated",
        type="number",
        description="How many rows matched a record and changed it.",
    ),
    IOSpec(
        name="unchanged",
        type="number",
        description="How many rows matched a record that already held their values.",
    ),
    IOSpec(
        name="skipped",
        type="number",
        description="How many rows were not saved.",
    ),
    IOSpec(
        name="skipped_rows",
        type="list",
        description="Why each row not saved was left out: no key value, a key "
        "repeated in the table, several records with that key, or a value the "
        "record refused.",
    ),
]


class Plugin(PluginBase):
    id = "civex.rows_to_records"
    name = "Make a record for each row"
    description = (
        "Save each table row as a record. With Match rows by (or a unique key "
        "on the kind of record), a row whose key matches a record already "
        "there updates that record instead, changing only the table's columns, "
        "so running the same table again changes nothing. With neither, every "
        "row makes a new record."
    )
    category = "outputs"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="table",
            type="table",
            description="The table to make records from. Its columns go into the fields of the same name, unless Columns to fields says otherwise.",
        )
    ]
    outputs = OUTPUTS

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "For each row of {table}, makes a {schema} inside this record, "
                "or updates the one already there with the same key."
            ),
            populate_by_name=True,
        )
        schema_name: str = Field(
            title="Kind of record to make",
            json_schema_extra=hint("schema"),
            alias="schema",
            description="Name of the schema to create records under. Workflow "
            "YAML sets this via the `schema:` key (the Python field is "
            "`schema_name`).",
        )
        match_on: list[str] = Field(
            title="Match rows by",
            json_schema_extra=hint("field", of="schema", many=True),
            default_factory=list,
            description="The fields (after Columns to fields) a row and a "
            "record must agree on to be the same record. Empty: the kind's "
            "first unique key, or, when it has none, every row makes a new "
            "record.",
        )
        dataset: str = Field(
            title="Collection",
            json_schema_extra=advanced(hint("collection")),
            default="",
            description="Dataset to create records in. Empty string falls back "
            "to the trigger record's own dataset.",
        )
        field_mapping: dict[str, str] = Field(
            title="Columns to fields",
            json_schema_extra=advanced(),
            default_factory=dict,
            description="Maps table column names to schema field names. Empty "
            "means columns are used as schema field names directly.",
        )
        context_record_id: str = Field(
            title="Inside record",
            json_schema_extra=advanced(hint("record")),
            default="",
            description="Parent record ID to match within and attach created "
            "records to. Empty string falls back to the workflow's context "
            "record.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        return save_rows(
            ctx,
            inputs["table"],
            schema_name=config.schema_name,
            dataset=config.dataset,
            match_on=config.match_on,
            mapping=config.field_mapping,
            parent_record_id=config.context_record_id,
        )
