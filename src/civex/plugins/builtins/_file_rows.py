r"""Saving files as records: the files half of `civex.save_records`.

Each file goes in a file field of a record. The record is found by a key in the
file's name (`filename_pattern` has one capture group; the captured text is
compared with the record's `match_on` field, "01" and "1" being the same
number), or, with `if_exists: add_new`, every file simply makes a new record.

A `file_list` field holds a list: the file is added to it (once) on a record
that has one, and is the whole list of a new record. A `file` field holds the
file itself, replacing any there. Two files in one run whose keys come out the
same would each be attached to the same record, the later replacing the earlier,
silently; that is almost always a pattern that reads too little of the name
(`sel_(\d{2})` takes "14" from selection 149 and from selection 14), so none of
them is attached: they are listed (`ambiguous`), and nothing wrong is written.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from civex_plugin_sdk import Ctx, RpcError

from civex.plugins.builtins._refusals import GONE, refused

log = logging.getLogger(__name__)

#: What a file does when a record with its key already exists.
UPDATE, SKIP, ADD_NEW = "update", "skip", "add_new"


def _normalise(key: str) -> str:
    """A captured key as the record's field is compared: "01" -> "1", so an
    integer field matches; anything else is left as it is."""
    try:
        return str(int(key))
    except ValueError:
        return key


def _with_file(current: Any, ref: dict[str, Any]) -> list[Any]:
    """A `file_list` value with `ref` added, unless the same content is there
    already (a run over the same files again changes nothing). A lone file
    stored before lists were enforced is read as a list of one."""
    files = current if isinstance(current, list) else [current] if current else []
    if any(isinstance(f, dict) and f.get("sha256") == ref.get("sha256") for f in files):
        return files
    return [*files, ref]


def save_files(
    ctx: Ctx,
    files: list[dict[str, Any]],
    *,
    schema_name: str,
    dataset: str,
    parent_record_id: str,
    file_field: str,
    if_exists: str,
    pattern: str,
    key_field: str,
) -> dict[str, Any]:
    dataset_name = dataset or ctx.get_context_dataset()["name"]
    parent_id = parent_record_id or ctx.get_context_record()["id"]

    pat = None
    if pattern:
        try:
            pat = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Invalid pattern '{pattern}': {e}")
        if pat.groups < 1:
            raise ValueError(
                f"Pattern '{pattern}' has no capture group -- it must have "
                "one, e.g. '(\\d+)', to take the key out of a file name."
            )
    matching = if_exists != ADD_NEW
    if matching and (pat is None or not key_field):
        raise ValueError(
            "To match files to records, say which field to match on (match_on) "
            "and which part of the file name holds the key (filename_pattern)."
        )

    log.info(
        "Saving %d file(s) -> %s.%s%s",
        len(files),
        schema_name,
        file_field,
        f" matched by '{pattern}'" if matching else " (each a new record)",
    )

    field_type = next(
        (
            f["dtype"]
            for f in ctx.get_schema(schema_name)["fields"]
            if f["name"] == file_field
        ),
        None,
    )
    if field_type not in ("file", "file_list"):
        raise ValueError(
            f"'{file_field}' is not a file field of '{schema_name}'"
            + (f" (it is {field_type})" if field_type else "")
        )
    as_list = field_type == "file_list"

    created = updated = unchanged = 0
    unmatched: list[str] = []
    ambiguous: list[str] = []
    skipped_rows: list[str] = []

    by_key: dict[str, list[str]] = {}
    if pat is not None and matching:
        for ref in files:
            name = ref.get("filename", "")
            found = pat.search(name)
            if found:
                by_key.setdefault(_normalise(found.group(1)), []).append(name)

    def create(ref: dict[str, Any], key_value: str | None) -> bool:
        data: dict[str, Any] = {file_field: [ref] if as_list else ref}
        if key_value is not None and key_field:
            try:
                typed: Any = int(key_value)
            except ValueError:
                typed = key_value
            data = {key_field: typed, **data}
        name = ref.get("filename", "?")
        try:
            child = ctx.create_record(
                dataset_name, schema_name, data, context_record_id=parent_id
            )
        except RpcError as e:
            if not refused(e):
                raise
            log.warning("  x cannot create %s from '%s': %s", schema_name, name, e)
            unmatched.append(f"{name} (not saved: {e})")
            return False
        log.info("  created '%s' -> %s %s", name, schema_name, child["id"][:8])
        return True

    for ref in files:
        filename = ref.get("filename", "")
        if not matching:
            m = pat.search(filename) if pat is not None else None
            created += create(ref, _normalise(m.group(1)) if m else None)
            continue
        assert pat is not None
        m = pat.search(filename)
        if not m:
            log.warning("Pattern did not match filename '%s'", filename)
            unmatched.append(filename)
            continue
        key_value = _normalise(m.group(1))
        clashing = by_key.get(key_value, [])
        if len(clashing) > 1:
            others = [n for n in clashing if n != filename]
            log.warning(
                "Skipped '%s': key %s is also the key of %d other file(s)",
                filename,
                key_value,
                len(others),
            )
            ambiguous.append(
                f"{filename} (key {key_value} is also in: {', '.join(others)})"
            )
            continue

        existing = ctx.find_records(
            dataset_name,
            schema_name=schema_name,
            parent_record_id=parent_id,
            filters=[f"{key_field}={key_value}"],
            limit=1,
        )
        if not existing:
            created += create(ref, key_value)
            continue
        child = existing[0]
        if if_exists == SKIP:
            skipped_rows.append(
                f"{filename}: {schema_name} with {key_field} {key_value} already "
                "exists, left as it is"
            )
            continue
        try:
            # Only the file field: the record's other values stay as they are now.
            value: Any = ref
            if as_list:
                value = _with_file(child["data"].get(file_field), ref)
            after = ctx.patch_record(child["id"], {file_field: value})
            if after.get("updated_at") == child.get("updated_at"):
                unchanged += 1
            else:
                updated += 1
        except RpcError as e:
            # A schema restriction violation, or the matched record being
            # deleted concurrently, reports this one file rather than aborting
            # the whole job.
            if not refused(e, GONE):
                raise
            log.warning("  x cannot update %s %s: %s", schema_name, child["id"][:8], e)
            unmatched.append(f"{filename} (could not update record: {e})")

    log.info(
        "Done: %d created, %d updated, %d unchanged, %d not saved, %d ambiguous",
        created,
        updated,
        unchanged,
        len(unmatched),
        len(ambiguous),
    )
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": len(unmatched) + len(ambiguous) + len(skipped_rows),
        "skipped_rows": skipped_rows,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
    }
