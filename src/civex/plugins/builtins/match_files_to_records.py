from __future__ import annotations

import logging
import re
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import NotFoundError, ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.match_files_to_records"
    name = "Match Files to Records"
    description = (
        "Attach each file to an existing child record matched by a key "
        "extracted from its filename, creating the record when none matches."
    )
    category = "outputs"
    capabilities: list[str] = ["create_record", "update_record", "find_records"]
    inputs = [IOSpec(name="files", type="files", description="FileRef dicts to match.")]
    outputs = [
        IOSpec(
            name="created",
            type="number",
            description="Records created because no match was found.",
        ),
        IOSpec(
            name="updated", type="number", description="Existing records given a file."
        ),
        IOSpec(
            name="unmatched",
            type="list",
            description="Filenames the pattern missed, or whose record could not be created.",
        ),
    ]

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(
            alias="schema",
            description="Name of the child schema to match/create records "
            "under. Workflow YAML sets this via the `schema:` key (the Python "
            "field is `schema_name`).",
        )
        key_field: str = Field(
            description="Field on child records to match the extracted key "
            "against, e.g. 'selection_number'."
        )
        file_field: str = Field(
            description="Field on child records to set with the matched file "
            "reference, e.g. 'contour_file'."
        )
        pattern: str = Field(
            description="Regex with one capture group that extracts the key "
            "value from each filename."
        )
        dataset: str = Field(
            default="",
            description="Dataset to search and create records in. Empty string "
            "falls back to the trigger record's own dataset.",
        )
        parent_record_id: str = Field(
            default="",
            description="Parent record ID to scope matching and creation to. "
            "Empty string falls back to the trigger record's ID.",
        )

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        files: list[dict[str, Any]] = inputs["files"]  # list of FileRef dicts
        dataset_name = config.dataset or ctx.dataset.name
        parent_id = config.parent_record_id or str(ctx.record.id)

        try:
            pat = re.compile(config.pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{config.pattern}': {e}")
        if pat.groups < 1:
            raise ValueError(
                f"Pattern '{config.pattern}' has no capture group -- it must "
                "have one, e.g. '(\\d+)', to extract the key value from a "
                "filename."
            )

        log.info(
            "Matching %d file(s) → %s.%s using pattern '%s'",
            len(files),
            config.schema_name,
            config.file_field,
            config.pattern,
        )

        created = updated = 0
        unmatched: list[str] = []

        for ref in files:
            filename = ref.get("filename", "")
            m = pat.search(filename)
            if not m:
                log.warning("Pattern did not match filename '%s'", filename)
                unmatched.append(filename)
                continue

            key_value = m.group(1)
            # Normalise numeric captures: "01" → "1" so integer fields match.
            try:
                key_value = str(int(key_value))
            except ValueError:
                pass

            existing = ctx.find_records(
                dataset_name,
                schema_name=config.schema_name,
                parent_record_id=parent_id,
                filters=[f"{config.key_field}={key_value}"],
                limit=1,
            )

            if existing:
                child = existing[0]
                try:
                    ctx.update_record(
                        str(child.id), {**child.data, config.file_field: ref}
                    )
                    log.info(
                        "  ✓ updated  '%s' → %s %s (key=%s)",
                        filename,
                        config.schema_name,
                        str(child.id)[:8],
                        key_value,
                    )
                    updated += 1
                except (ValidationError, NotFoundError) as e:
                    # Symmetric with the create branch below: a schema
                    # restriction violation, or the matched record being
                    # deleted concurrently, should report this one file as
                    # unmatched rather than abort the whole job.
                    log.warning(
                        "  ✗ cannot update %s %s (key=%s): %s",
                        config.schema_name,
                        str(child.id)[:8],
                        key_value,
                        e,
                    )
                    unmatched.append(f"{filename} (could not update record: {e})")
            else:
                try:
                    typed_key: Any = int(key_value)
                except ValueError:
                    typed_key = key_value
                try:
                    child = ctx.create_record(
                        dataset_name,
                        config.schema_name,
                        {config.key_field: typed_key, config.file_field: ref},
                        context_record_id=parent_id,
                    )
                    log.info(
                        "  ✓ created  '%s' → %s %s (key=%s)",
                        filename,
                        config.schema_name,
                        str(child.id)[:8],
                        key_value,
                    )
                    created += 1
                except ValidationError as e:
                    log.warning(
                        "  ✗ cannot create %s (key=%s): %s",
                        config.schema_name,
                        key_value,
                        e,
                    )
                    unmatched.append(f"{filename} (missing required fields: {e})")

        log.info(
            "Done: %d created, %d updated, %d unmatched",
            created,
            updated,
            len(unmatched),
        )
        if unmatched:
            log.warning("Unmatched files: %s", unmatched)

        return {"created": created, "updated": updated, "unmatched": unmatched}
