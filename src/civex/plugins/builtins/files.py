from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from civex.domain.exceptions import ValidationError
from civex.domain.features import SERVER_PATH_IMPORT
from civex.plugins.hints import hint, says, when

log = logging.getLogger(__name__)

#: What a run is given for a Files step set to "Chosen when the workflow is
#: run" (the run's `__input__.<step id>`): the files already stored, or a
#: folder on this computer to read them from.
PROVIDED = "provided"


class Plugin(PluginBase):
    id = "civex.files@1"
    name = "Files"
    description = (
        "Bring in files. Choose them each time the workflow is run (drop them "
        "in, or point at a folder on this computer), read a folder you name "
        "here, or use the files in a field of the record the workflow runs on."
    )
    category = "bring-in"
    capabilities: list[str] = ["read", "store_folder"]
    inputs = [
        IOSpec(
            name=PROVIDED,
            type="any",
            required=False,
            description="What was chosen when the workflow was run. Filled in "
            "by civex; leave it out.",
        )
    ]
    outputs = [
        IOSpec(name="files", type="files", description="The files brought in."),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "Brings in files: {source}. They can be used by the steps after this one."
            )
        )
        source: str = Field(
            title="Where the files come from",
            json_schema_extra=hint(
                "choice",
                choices=[
                    {"value": "run", "label": "Chosen when the workflow is run"},
                    {
                        "value": "folder",
                        "label": "A folder on this computer",
                        "feature": SERVER_PATH_IMPORT,
                    },
                    {"value": "field", "label": "A field of this record"},
                ],
            ),
            default="run",
            description="run: picked each time the workflow is run. folder: the "
            "folder named in `folder`. field: the files in the record's `field`.",
        )
        label: str | None = Field(
            title="What to ask for",
            json_schema_extra=when("source", "run"),
            default=None,
            description="What the person running the workflow is asked for, "
            "e.g. 'Sequence WAV files'.",
        )
        folder: str | None = Field(
            title="Folder",
            json_schema_extra=when("source", "folder", extra=hint("folder")),
            default=None,
            description="The folder on this computer to read files from "
            "(source: folder). Reading a folder is not offered by a server "
            "hosting other people's projects.",
        )
        glob: str = Field(
            title="Only files named like",
            json_schema_extra=when("source", "folder"),
            default="*",
            description="Which files in the folder to take, e.g. *.wav.",
        )
        subfolders: bool = Field(
            title="Include subfolders",
            json_schema_extra=when("source", "folder"),
            default=False,
            description="Also take files in the folders inside the folder.",
        )
        field: str | None = Field(
            title="Field",
            json_schema_extra=when(
                "source", "field", extra=hint("field", dtypes=["file", "file_list"])
            ),
            default=None,
            description="The file or files field of the record the workflow runs on (source: field).",
        )

        @model_validator(mode="after")
        def _what_each_source_needs(self) -> "Plugin.Config":
            if self.source not in ("run", "folder", "field"):
                raise ValueError("source must be run, folder or field")
            if self.source == "folder" and not self.folder:
                raise ValueError("Say which folder to read (folder).")
            if self.source == "field" and not self.field:
                raise ValueError("Say which field holds the files (field).")
            return self

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        if config.source == "field":
            return {"files": _field_files(ctx, str(config.field))}
        if config.source == "folder":
            return {"files": _folder_files(ctx, str(config.folder), config)}
        provided = inputs.get(PROVIDED)
        if provided is None:
            raise ValidationError(
                "No files were chosen for this step. Choose files, or a folder, "
                "when you run the workflow."
            )
        if isinstance(provided, dict):
            return {
                "files": _folder_files(
                    ctx,
                    str(provided.get("folder") or ""),
                    glob=str(provided.get("glob") or "*"),
                    subfolders=bool(provided.get("subfolders")),
                )
            }
        return {"files": list(provided)}


def _field_files(ctx: Ctx, field: str) -> list[dict[str, Any]]:
    raw = ctx.get_context_record()["data"].get(field)
    if not raw:
        log.warning("Field '%s' is empty or missing: no files to process", field)
        return []
    if isinstance(raw, dict) and "sha256" in raw:
        return [raw]  # a single file field
    if isinstance(raw, list):
        return raw
    raise ValueError(f"Field '{field}' does not hold files (got {type(raw).__name__})")


def _folder_files(
    ctx: Ctx,
    folder: str,
    config: Any = None,
    *,
    glob: str = "*",
    subfolders: bool = False,
) -> list[dict[str, Any]]:
    if config is not None:
        glob, subfolders = config.glob, config.subfolders
    result = ctx._call_tool(
        "store_folder", {"folder": folder, "pattern": glob, "subfolders": subfolders}
    )
    log.info(
        "Read %d file(s) from %s (%d already stored)",
        len(result["files"]),
        folder,
        result["already_stored"],
    )
    return result["files"]
