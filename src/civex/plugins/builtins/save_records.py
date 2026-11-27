from __future__ import annotations

from typing import Any

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import ValidationError
from civex.plugins.builtins._file_rows import save_files
from civex.plugins.builtins._table_rows import save_rows
from civex.plugins.hints import advanced, choices, hint, says

IF_EXISTS = ("update", "skip", "add_new")


class Plugin(PluginBase):
    id = "civex.save_records@1"
    name = "Save as records"
    description = (
        "Save the rows of a table, or a set of files, as records: one record "
        "for each row or file. Choose what happens when a matching record "
        "already exists: update it (changing only what the table or file "
        "brings), leave it alone, or add another. Running the same table or "
        "files again changes nothing."
    )
    category = "save"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="rows",
            type="table",
            required=False,
            description="The table to save, one record for each row. Its "
            "columns go into the fields of the same name, unless Columns to "
            "fields says otherwise.",
        ),
        IOSpec(
            name="files",
            type="files",
            required=False,
            description="The files to save, one record for each file, with the "
            "file in the field chosen in Put the file in field.",
        ),
        IOSpec(
            name="earlier",
            type="table",
            required=False,
            description="Rows that come before the table, already dealt with "
            "(same columns): their keys count when a repeated one is looked "
            "for, so a table saved in parts treats repeats as one saved whole. "
            "Nothing is saved from them.",
        ),
    ]
    outputs = [
        IOSpec(name="created", type="number", description="How many records it made."),
        IOSpec(
            name="updated",
            type="number",
            description="How many existing records it changed.",
        ),
        IOSpec(
            name="unchanged",
            type="number",
            description="How many existing records already held what was brought.",
        ),
        IOSpec(
            name="skipped",
            type="number",
            description="How many rows or files were not saved.",
        ),
        IOSpec(
            name="skipped_rows",
            type="list",
            description="Why each row or file not saved was left out: no value "
            "to match by, a value repeated, several records with it, a matching "
            "record left alone, or a value the record refused.",
        ),
        IOSpec(
            name="unmatched",
            type="list",
            required=False,
            description="Files with no key in their name, or whose record "
            "could not be saved.",
        ),
        IOSpec(
            name="ambiguous",
            type="list",
            required=False,
            description="Files left alone because another file in the same run "
            "has the same key (one record holds one file), each with the files "
            "it clashes with.",
        ),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "Saves {rows} or {files} as {schema} records inside this record. "
                "If a matching record already exists: {if_exists}."
            ),
            populate_by_name=True,
        )
        schema_name: str = Field(
            title="Kind of record",
            json_schema_extra=hint("schema"),
            alias="schema",
            description="The kind of record to save. In the YAML, `schema:`.",
        )
        if_exists: str = Field(
            title="If a matching record already exists",
            json_schema_extra=choices(
                ("update", "Update it"),
                ("skip", "Leave it alone"),
                ("add_new", "Add another record"),
            ),
            default="update",
            description="update: change the record, only what the table or file "
            "brings. skip: leave it as it is. add_new: always make a new "
            "record, never looking for a match.",
        )
        match_on: list[str] = Field(
            title="Match on",
            json_schema_extra=hint("field", of="schema", many=True),
            default_factory=list,
            description="The field(s) a row or file and a record must agree on "
            "to be the same record. For a table, empty means the kind's first "
            "unique key, or, when it has none, every row makes a new record. "
            "For files, one field, compared with the key in the file's name.",
        )
        filename_pattern: str | None = Field(
            title="The key in each file's name",
            json_schema_extra=hint("pattern", on="files", keys=True),
            default=None,
            description="Files only: which part of a file's name says which "
            "record it belongs to, with one capture group, e.g. sel_(\\d+). "
            "Build it from an example.",
        )
        file_field: str | None = Field(
            title="Put the file in field",
            json_schema_extra=hint("field", of="schema", dtypes=["file", "file_list"]),
            default=None,
            description="Files only: the file field of each record.",
        )
        field_mapping: dict[str, str] = Field(
            title="Columns to fields",
            json_schema_extra=advanced(),
            default_factory=dict,
            description="Tables only: maps table column names to field names. "
            "Empty means columns are used as field names directly.",
        )
        as_written: bool = Field(
            title="Values are as a spreadsheet shows them",
            json_schema_extra=advanced(),
            default=False,
            description="Tables only: every cell is the text it shows. Blank "
            "cells are left out and each other cell becomes the value its field "
            "holds (a whole number, a date, yes or no); a row with a cell that "
            "can't be that is skipped and named.",
        )
        first_row: int = Field(
            title="Number of the first row",
            json_schema_extra=advanced(),
            default=1,
            ge=1,
            description="Tables only: the number said of the first row when a "
            "row is named (2 for the first row under a heading row).",
        )
        dataset: str = Field(
            title="Collection",
            json_schema_extra=advanced(hint("collection")),
            default="",
            description="Collection to save records in. Empty: the collection "
            "of the record the workflow runs on.",
        )
        parent_record_id: str = Field(
            title="Inside record",
            json_schema_extra=advanced(hint("record")),
            default="",
            description="The record to match within and save inside. Empty: the "
            "record the workflow runs on.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        if config.if_exists not in IF_EXISTS:
            raise ValidationError(
                f"'If a matching record already exists' must be one of "
                f"{', '.join(IF_EXISTS)} (got '{config.if_exists}')."
            )
        rows = inputs.get("rows")
        files: list[dict[str, Any]] | None = inputs.get("files")
        if (rows is None) == (files is None):
            raise ValidationError(
                "Connect either a table (rows) or files, not both and not neither."
            )
        if rows is not None:
            return save_rows(
                ctx,
                rows,
                schema_name=config.schema_name,
                dataset=config.dataset,
                match_on=config.match_on,
                mapping=config.field_mapping,
                parent_record_id=config.parent_record_id,
                if_exists=config.if_exists,
                as_written=config.as_written,
                first_row=config.first_row,
                earlier=inputs.get("earlier"),
            )
        if not config.file_field or files is None:
            raise ValidationError("Say which field the file goes in (file_field).")
        return save_files(
            ctx,
            files,
            schema_name=config.schema_name,
            dataset=config.dataset,
            parent_record_id=config.parent_record_id,
            file_field=config.file_field,
            if_exists=config.if_exists,
            pattern=config.filename_pattern or "",
            key_field=config.match_on[0] if config.match_on else "",
        )
