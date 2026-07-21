from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from civex.domain.exceptions import ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)


class Plugin(Tier0Plugin):
    id = "civex.match_files_to_records"
    name = "Match Files to Records"
    category = "outputs"
    capabilities: list[str] = ["create_record", "update_record", "find_records"]

    class Config(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        schema_name: str = Field(alias="schema")
        key_field: (
            str  # field on child records to match against (e.g. selection_number)
        )
        file_field: str  # field on child records to set (e.g. contour_file)
        pattern: str  # regex with one capture group for the key value
        dataset: str = ""  # defaults to ctx.dataset.name
        parent_record_id: str = ""  # defaults to ctx.record.id

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
                ctx.update_record(str(child.id), {**child.data, config.file_field: ref})
                log.info(
                    "  ✓ updated  '%s' → %s %s (key=%s)",
                    filename,
                    config.schema_name,
                    str(child.id)[:8],
                    key_value,
                )
                updated += 1
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
