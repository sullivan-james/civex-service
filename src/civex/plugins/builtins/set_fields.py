from __future__ import annotations

import logging
from typing import Any

from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.plugins.hints import advanced, hint, says

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    id = "civex.set_fields@1"
    name = "Set fields on this record"
    description = (
        "Fill in fields of the record the workflow runs on, with values you "
        "type here, values from other fields of the record, or values worked "
        "out by earlier steps. Only the fields named change; the record's "
        "other fields are kept."
    )
    category = "save"
    capabilities: list[str] = ["read", "write_records"]
    inputs = [
        IOSpec(
            name="value",
            type="any",
            required=False,
            description="One value, put in the field named in the Field setting.",
        ),
        IOSpec(
            name="updates",
            type="mapping",
            required=False,
            description="Several values, by field (field: value). Empty values "
            "are left alone.",
        ),
    ]
    outputs: list[IOSpec] = []

    class Config(BaseModel):
        model_config = ConfigDict(json_schema_extra=says("Sets fields on this record."))
        fields: dict[str, Any] = Field(
            title="Fields to set",
            default_factory=dict,
            description="The fields to set and what to put in each: a value, "
            "or {from_field: other_field} to copy another field of this record.",
        )
        field: str | None = Field(
            title="Field for the value input",
            json_schema_extra=advanced(hint("field")),
            default=None,
            description="The field that the `value` input is put in.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        changes: dict[str, Any] = dict(config.fields)
        # Values from earlier steps: empty ones are left alone, so a missing
        # value never clears a field.
        for name, value in (inputs.get("updates") or {}).items():
            if value is not None:
                changes[name] = value
        if "value" in inputs:
            if not config.field:
                raise ValueError("Say which field the value goes in (field).")
            changes[config.field] = inputs["value"]
        # Only these fields change; the others are read as they are now, not as
        # they were when the workflow started.
        record_id = ctx.get_context_record()["id"]
        log.info(
            "Setting %d field(s) on record %s: %s",
            len(changes),
            record_id[:8],
            list(changes),
        )
        if changes:
            ctx.patch_record(record_id, changes)
        return {}
