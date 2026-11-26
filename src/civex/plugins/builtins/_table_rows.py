"""Saving a table's rows as records: the rows half of `civex.save_records`.

With `if_exists: add_new`, or no key, every row makes a new record (a pure
insert). With `skip`, a row whose record exists is left alone (and named). With a key (the
fields named in *Match rows by*, else the kind's first unique key), a row is
the same record as one already inside the same record (or at the top of the
collection) whose key fields hold the row's values, compared the way a unique
key compares them (`RecordRepository.find_key_match`'s typed equality: 12 is
12.0, "12" is not 12). A matched record gets only the row's fields
(`patch_record`: nothing is written when they already hold those values), so
running the same table again changes nothing, leaves no history and starts
no workflows. A row with a blank key, a row repeating an earlier row's key,
and a row matching more than one record are skipped and named, never
guessed at.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from civex_plugin_sdk import Ctx, RpcError

from civex.domain.table_import import coerce_cell
from civex.domain.uniqueness import UNIQUE_DTYPES, is_blank
from civex.plugins.builtins._refusals import GONE, refused

log = logging.getLogger(__name__)

#: The types a row can be matched by: those a unique key can be made of, and
#: long text, compared whole.
_MATCHABLE = UNIQUE_DTYPES | {"longtext"}

#: Rows named in `skipped_rows` at most; the count stays exact.
MAX_NAMED = 200


@dataclass
class Outcome:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    skipped_rows: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped += 1
        if len(self.skipped_rows) < MAX_NAMED:
            self.skipped_rows.append(why)

    def outputs(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "skipped_rows": self.skipped_rows,
        }


def match_key(ctx: Ctx, schema_name: str, match_on: list[str]) -> dict[str, str]:
    """The fields rows are matched by, with their types: `match_on` when given
    (each must be a field of the kind's own, of a type that compares as one
    value), else the kind's first unique key, else none (every row makes a
    new record)."""
    schema = ctx.get_schema(schema_name)
    own = {
        f["name"]: f
        for f in schema.get("fields", [])
        if f.get("schema_id") == schema["id"]
    }
    if not match_on:
        by_id = {f["id"]: name for name, f in own.items()}
        for key in schema.get("unique_keys") or []:
            if all(i in by_id for i in key):
                names = [by_id[i] for i in key]
                log.info(
                    "Matching rows by %s, the unique key of '%s'",
                    ", ".join(names),
                    schema_name,
                )
                return {n: own[n]["dtype"] for n in names}
        return {}
    key = list(dict.fromkeys(match_on))
    for name in key:
        f = own.get(name)
        if f is None:
            inherited = any(x["name"] == name for x in schema.get("fields", []))
            raise ValueError(
                f"Can't match rows by '{name}': "
                + (
                    f"it belongs to the record above a '{schema_name}', not to "
                    f"the '{schema_name}' itself"
                    if inherited
                    else f"'{schema_name}' has no such field"
                )
            )
        if f["dtype"] not in _MATCHABLE:
            raise ValueError(
                f"Can't match rows by '{name}': a {f['dtype']} field can't be "
                "compared as one value"
            )
    return {n: own[n]["dtype"] for n in key}


def _plain(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _row_data(
    row: Any, columns: list[str], mapping: dict[str, str], as_written: bool = False
) -> dict:
    import pandas as pd

    if mapping:
        raw = {
            schema_field: row[column]
            for column, schema_field in mapping.items()
            if column in row
        }
    else:
        raw = {column: row[column] for column in columns}
    return {
        k: _plain(v)
        for k, v in raw.items()
        if not pd.isna(v) and not (as_written and is_blank(v))
    }


#: Types whose values are text: a number a table gives for one is written,
#: and matched, as its text ("12", never 12.0), so it compares with the text
#: stored (and PostgreSQL never casts stored text to a number).
_TEXT = frozenset({"string", "enum", "url", "longtext", "date", "datetime"})


def _as_text(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _same(value: Any) -> Any:
    """A key value as a unique key compares it: numbers by value (12 and
    12.0 are one), a boolean apart from the numbers 1 and 0."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return ("number", float(value))
    return ("text", value)


def _said(key: dict[str, str], values: list[Any]) -> str:
    return ", ".join(f"{k} {v!r}" for k, v in zip(key, values))


#: Existing records asked for in one question; a longer batch is asked in parts.
_LOOKUP = 200
#: Records one answer holds at most; a longer answer is read in pages.
_PAGE = 1000


def _found(
    ctx: Ctx,
    dataset: str,
    schema_name: str,
    parent_id: str,
    key: dict[str, str],
    batch: list[list[Any]],
) -> dict[tuple, list[dict[str, Any]]]:
    """The records already in the rows' place holding any of the key values in
    `batch`, grouped by the key they hold, as a unique key compares them.
    Asked a batch at a time with the explorer's typed filter (`filter_tree`),
    never a row at a time: one question for a few hundred rows."""
    names = list(key)
    found: dict[tuple, list[dict[str, Any]]] = {}
    for at in range(0, len(batch), _LOOKUP):
        part = batch[at : at + _LOOKUP]
        if len(names) == 1:
            tree: dict[str, Any] = {
                "and": [{"field": names[0], "op": "in", "value": [v[0] for v in part]}]
            }
        else:
            tree = {
                "or": [
                    {
                        "and": [
                            {"field": n, "op": "eq", "value": v}
                            for n, v in zip(names, values)
                        ]
                    }
                    for values in part
                ]
            }
        offset = 0
        while True:
            # `Ctx.find_records` doesn't send a filter tree yet in the released
            # SDK, so the host function is asked for directly.
            page = ctx._call_tool(
                "find_records",
                {
                    "dataset_name": dataset,
                    "schema_name": schema_name,
                    "parent_record_id": parent_id,
                    "filter_tree": tree,
                    "limit": _PAGE,
                    "offset": offset,
                },
            )["records"]
            for record in page:
                data = record.get("data", {})
                marker = tuple(_same(data.get(n)) for n in names)
                found.setdefault(marker, []).append(record)
            if len(page) < _PAGE:
                break
            offset += _PAGE
    return found


def save_rows(
    ctx: Ctx,
    df: Any,
    *,
    schema_name: str,
    dataset: str,
    match_on: list[str],
    mapping: dict[str, str],
    parent_record_id: str,
    if_exists: str = "update",
    as_written: bool = False,
    first_row: int = 1,
    earlier: Any = None,
) -> dict[str, Any]:
    """Save the rows. `as_written`: the cells are text as a spreadsheet shows
    them, so blanks are left out and each cell becomes the value its field
    holds (`coerce_cell`), a row with a cell that can't be one is skipped and
    named. `first_row` numbers the rows in what is said about them (a part of
    a table read later starts higher), and `earlier` is the rows before them
    (same columns), whose keys count when a repeated one is looked for: a table
    saved in parts skips a repeated key the way one saved whole does."""
    dataset_name = dataset or ctx.get_context_dataset()["name"]
    schema = ctx.get_schema(schema_name)
    key = {} if if_exists == "add_new" else match_key(ctx, schema_name, match_on)
    # A kind with no parent is at the top of its collection: there is no
    # record to match within or save inside.
    if parent_record_id or schema.get("parent_id"):
        parent_id = parent_record_id or ctx.get_context_record()["id"]
    else:
        parent_id = ""
    types = {f["name"]: f["dtype"] for f in schema.get("fields", []) if "dtype" in f}
    columns = list(df.columns)
    log.info(
        "Saving %d rows → collection '%s', kind '%s'%s",
        len(df),
        dataset_name,
        schema_name,
        f", matched by {', '.join(key)}" if key else " (each a new record)",
    )

    def _clean(row: Any) -> tuple[dict[str, Any], list[str]]:
        """The row's values for its fields, and what is wrong with any."""
        data = _row_data(row, columns, mapping, as_written)
        wrong: list[str] = []
        if as_written:
            for name in list(data):
                try:
                    data[name] = coerce_cell(data[name], types.get(name, "string"))
                except ValueError as e:
                    wrong.append(f"{name}: {e}")
        for name, dtype in key.items():
            if dtype in _TEXT and name in data:
                data[name] = _as_text(data[name])
        return data, wrong

    seen: dict[tuple, int] = {}
    if earlier is not None and key:
        for at, (_, row) in enumerate(earlier.iterrows()):
            data, wrong = _clean(row)
            values = [data.get(name) for name in key]
            if wrong or any(is_blank(v) for v in values):
                continue
            seen.setdefault(
                tuple(_same(v) for v in values), first_row - len(earlier) + at
            )

    prepared: list[tuple[int, dict[str, Any], list[str]]] = []
    for at, (_, row) in enumerate(df.iterrows()):
        data, wrong = _clean(row)
        prepared.append((first_row + at, data, wrong))
    existing: dict[tuple, list[dict[str, Any]]] = {}
    if key:
        ask: dict[tuple, list[Any]] = {}
        for _, data, wrong in prepared:
            values = [data.get(name) for name in key]
            if not wrong and not any(is_blank(v) for v in values):
                marker = tuple(_same(v) for v in values)
                if marker not in seen:
                    ask.setdefault(marker, values)
        if ask:
            existing = _found(
                ctx, dataset_name, schema_name, parent_id, key, list(ask.values())
            )

    out = Outcome()
    for number, data, wrong in prepared:
        try:
            if wrong:
                out.skip(f"Row {number}: {'; '.join(wrong)}")
                continue
            if as_written and not data:
                continue  # a row with nothing in it is not a record
            if not key:
                ctx.create_record(dataset_name, schema_name, data, parent_id)
                out.created += 1
                continue
            values = [data.get(name) for name in key]
            blank = [name for name, v in zip(key, values) if is_blank(v)]
            if blank:
                out.skip(f"Row {number}: no {', '.join(blank)} to match it by")
                continue
            marker = tuple(_same(v) for v in values)
            if marker in seen:
                out.skip(
                    f"Row {number}: {_said(key, values)} is also row "
                    f"{seen[marker]}, which was saved"
                )
                continue
            seen[marker] = number
            found = existing.get(marker, [])
            if len(found) > 1:
                out.skip(
                    f"Row {number}: several records already have {_said(key, values)}"
                )
                continue
            if not found:
                ctx.create_record(dataset_name, schema_name, data, parent_id)
                out.created += 1
                continue
            if if_exists == "skip":
                out.skip(
                    f"Row {number}: a record with {_said(key, values)} already "
                    "exists, left as it is"
                )
                continue
            before = found[0]
            after = ctx.patch_record(before["id"], data)
            if after.get("updated_at") == before.get("updated_at"):
                out.unchanged += 1
            else:
                out.updated += 1
        except RpcError as e:
            # GONE too: a matched record can be deleted between finding and
            # saving it (another step, a person); the row is skipped like any
            # refused one rather than ending the run.
            if not refused(e, GONE):
                raise
            log.warning("  ✗ skipped row %d: %s", number, e)
            out.skip(f"Row {number}: {e}")
    log.info(
        "Done: %d created, %d updated, %d unchanged, %d skipped",
        out.created,
        out.updated,
        out.unchanged,
        out.skipped,
    )
    if out.skipped_rows:
        log.warning("Skipped rows: %s", out.skipped_rows)
    return out.outputs()
