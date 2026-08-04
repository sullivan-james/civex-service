"""Converts declared `table`/`bytes` IOSpec values between the invoke-time form and the always-JSON-safe wire form.

The invoke-time form is what a plugin author writes (a pandas DataFrame,
raw `bytes`); the wire form is what's always safe to put in a
`RunRequest`/`RunResult` and hand to another step.

`bytes` crosses the wire as the same `{"encoding": "base64"|"path", ...}`
envelope `civex_plugin_sdk.protocol.encode_binary`/`get_file` already use --
inlined under `BINARY_INLINE_THRESHOLD`, written to `scratch_dir` and
referenced by path above it. `table` crosses as a columnar, typed envelope:
`{"encoding": "inline", "columns": [...], "dtypes": {col: civex_type}, "data":
{col: [values...]}}` under `TABLE_INLINE_ROW_THRESHOLD` rows, or
`{"encoding": "ndjson_path", "path": "..."}` above it (one JSON row object per
line, first line a `{"columns": ..., "dtypes": ...}` header) -- so the host
and any step that's merely relaying a table between two other steps never has
to hold or embed the full content, only whichever step actually reads it does.
`dtypes` reuses civex's own scalar field vocabulary (integer/float/string/
boolean/date/datetime -- see CLAUDE.md's Field dtype table), not a
pandas-specific one, so it means the same thing here as everywhere else in
civex and round-trips through non-Python tiers without any pandas-specific
knowledge.

This is the one place either conversion happens, called identically from
civex-service's Tier0 registration closure (`civex.plugins.registry`) and
this package's own `serve._handle_run` (Tier 1, and the reserved Tier 2
Python-container path that reuses it) -- so an author's plugin code never has
to know or care which tier it's running on, and the wire itself never carries
anything but plain JSON regardless of which language wrote it.

Read-side (`to_invoke_form`) stays permissive: a plain `list[dict]` (an older
plugin's output, or a value a workflow/API caller supplied directly) is still
accepted and converted the old way. Only the write side (`to_wire_form`)
always produces the new envelope -- so this is additive for anything already
producing bare records, and only genuinely breaking for code that inspected
the previous wire shape directly (see the `civex-plugin-sdk`/`civex-service`
test suites for the handful of places that did).

Kept out of `plugin_base.py`, which documents itself as depending on nothing
but pydantic -- pandas is only ever imported lazily, inside a function, and
only when a `table` value actually needs it.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civex_plugin_sdk.protocol import decode_binary, encode_binary

if TYPE_CHECKING:
    from civex_plugin_sdk.plugin_base import IOSpec

# Above this many rows, a table is written to a scratch NDJSON file instead
# of being inlined in the RunRequest/RunResult JSON. Keyed on row count
# rather than bytes: a table's eventual JSON size depends heavily on column
# count/width, and counting rows is free (len()) where estimating serialized
# bytes up front would mean either a wasteful full-serialization pass or a
# pandas memory_usage() call that's a worse proxy for JSON size than it
# sounds. 10,000 rows is comfortably inline-sized (low hundreds of KB to a
# few MB for the typical handful-of-columns case) -- this is a guard against
# runaway huge tables, not a precise byte budget.
TABLE_INLINE_ROW_THRESHOLD = 10_000

_CIVEX_SCALAR_TYPES = ("integer", "float", "string", "boolean", "date", "datetime")


def _is_dataframe(value: Any) -> bool:
    # Duck-typed so this needs no pandas import just to check -- mirrors the
    # existing convention in civex-service's executor._json_safe.
    return hasattr(value, "columns") and hasattr(value, "shape")


# -- dtype inference: pandas DataFrame column -> civex's own scalar vocabulary


def _pandas_column_civex_type(series: Any) -> str:
    import pandas as pd

    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    non_null = series.dropna()
    if len(non_null) and all(type(v) is _dt.date for v in non_null):
        return "date"
    return "string"


def _pandas_series_to_wire_values(series: Any, civex_type: str) -> list[Any]:
    import pandas as pd

    if civex_type == "datetime":
        as_dt = pd.to_datetime(series, utc=True)
        return [None if pd.isna(v) else v.isoformat() for v in as_dt]
    if civex_type == "date":
        return [None if v is None else v.isoformat() for v in series]
    if civex_type in ("integer", "float", "boolean"):
        return [
            None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
            for v in series
        ]
    return [None if pd.isna(v) else str(v) for v in series]


def _dataframe_to_columnar(df: Any) -> dict[str, Any]:
    columns = [str(c) for c in df.columns]
    dtypes: dict[str, str] = {}
    data: dict[str, list[Any]] = {}
    for c in df.columns:
        name = str(c)
        civex_type = _pandas_column_civex_type(df[c])
        dtypes[name] = civex_type
        data[name] = _pandas_series_to_wire_values(df[c], civex_type)
    return {"columns": columns, "dtypes": dtypes, "data": data}


# -- dtype inference: plain list[dict] -> civex's own scalar vocabulary,
# for when there's no DataFrame (or no pandas) to read a real dtype from --
# e.g. an R/Java plugin's own hand-built table, or a Python plugin without
# the `[table]` extra installed.


def _python_value_civex_type(value: Any) -> str | None:
    """Best-effort type of a single JSON-decoded value.

    None for a value that doesn't narrow the guess (null).
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass -- check first
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, _dt.datetime):
        return "datetime"
    if isinstance(value, _dt.date):
        return "date"
    return "string"


def _records_columns_and_dtypes(
    records: list[dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Column order (first-seen across all rows) and a best-effort civex dtype per column.

    The dtype is inferred from whichever row happens to have that column's
    first non-null value. A column that's all-null (or empty) falls back to
    "string".
    """
    columns: list[str] = []
    seen: set[str] = set()
    dtypes: dict[str, str] = {}
    for row in records:
        for name, value in row.items():
            if name not in seen:
                seen.add(name)
                columns.append(name)
            if name not in dtypes:
                guessed = _python_value_civex_type(value)
                if guessed is not None:
                    dtypes[name] = guessed
    for name in columns:
        dtypes.setdefault(name, "string")
    return columns, dtypes


def _records_to_columnar(records: list[dict[str, Any]]) -> dict[str, Any]:
    columns, dtypes = _records_columns_and_dtypes(records)
    data = {c: [row.get(c) for row in records] for c in columns}
    return {"columns": columns, "dtypes": dtypes, "data": data}


# -- reconstruction: columnar wire data -> invoke-time value -----------------


def _columnar_to_dataframe(
    columns: list[str], dtypes: dict[str, str], data: dict[str, list[Any]]
) -> Any:
    import pandas as pd

    df = pd.DataFrame({c: data.get(c, []) for c in columns})
    for c in columns:
        civex_type = dtypes.get(c, "string")
        if civex_type == "datetime":
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
        elif civex_type == "date":
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        elif civex_type == "integer":
            df[c] = pd.array(df[c], dtype="Int64")
        elif civex_type == "float":
            df[c] = df[c].astype("float64")
        elif civex_type == "boolean":
            df[c] = pd.array(df[c], dtype="boolean")
        # "string" (or an unrecognized tag from a newer SDK): left as-is.
    return df


def _columnar_to_records(
    columns: list[str], data: dict[str, list[Any]]
) -> list[dict[str, Any]]:
    """Pandas-free reconstruction -- used when pandas isn't installed."""
    row_count = max((len(v) for v in data.values()), default=0)
    return [
        {c: (data.get(c) or [None] * row_count)[i] for c in columns}
        for i in range(row_count)
    ]


# -- large-table scratch file (NDJSON: one header line, then one row/line) --


def _write_ndjson_table(
    scratch_dir: Path, columns: list[str], dtypes: dict[str, str], rows: Any
) -> Path:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    # .resolve(): a relative scratch_dir (e.g. Path(".") -- a Tier 1
    # plugin's own cwd, see serve.py's _handle_run) is only meaningful
    # relative to *this* process. The path in the envelope crosses to
    # another process (the host, or a later step) with a different cwd, so
    # it must be absolute or it silently resolves to the wrong file there.
    path = (scratch_dir / f"{uuid.uuid4().hex}.ndjson").resolve()
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"columns": columns, "dtypes": dtypes}) + "\n")
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    return path


def _read_ndjson_table(
    path: Path,
) -> tuple[list[str], dict[str, str], dict[str, list[Any]]]:
    with path.open("r", encoding="utf-8") as f:
        header = json.loads(f.readline())
        columns, dtypes = header["columns"], header["dtypes"]
        data: dict[str, list[Any]] = {c: [] for c in columns}
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for c in columns:
                data[c].append(row.get(c))
    return columns, dtypes, data


def _dataframe_row_dicts(df: Any, columns: list[str], dtypes: dict[str, str]) -> Any:
    """Row-by-row generator for the NDJSON scratch-file path.

    Avoids ever building the whole table as one big in-memory list of dicts
    just to write it out one line at a time.
    """
    for _, row in df.iterrows():
        yield _row_to_wire_dict(row, columns, dtypes)


def _row_to_wire_dict(row: Any, columns: list[str], dtypes: dict[str, str]) -> dict:
    import pandas as pd

    out: dict[str, Any] = {}
    for c in columns:
        v = row[c]
        if pd.isna(v):
            out[c] = None
        elif dtypes.get(c) in ("datetime", "date"):
            out[c] = v.isoformat() if hasattr(v, "isoformat") else v
        elif hasattr(v, "item"):
            out[c] = v.item()
        else:
            out[c] = v
    return out


# -- table: wire <-> invoke -----------------------------------------------


def _table_to_wire_form(value: Any, scratch_dir: Path | None) -> Any:
    if isinstance(value, dict) and value.get("encoding") in ("inline", "ndjson_path"):
        return value  # already the envelope shape, e.g. author-built directly

    if _is_dataframe(value):
        if scratch_dir is not None and len(value) > TABLE_INLINE_ROW_THRESHOLD:
            columns = [str(c) for c in value.columns]
            dtypes = {c: _pandas_column_civex_type(value[c]) for c in columns}
            path = _write_ndjson_table(
                scratch_dir,
                columns,
                dtypes,
                _dataframe_row_dicts(value, columns, dtypes),
            )
            return {"encoding": "ndjson_path", "path": str(path)}
        return {"encoding": "inline", **_dataframe_to_columnar(value)}

    if isinstance(value, list):
        if scratch_dir is not None and len(value) > TABLE_INLINE_ROW_THRESHOLD:
            columns, dtypes = _records_columns_and_dtypes(value)
            path = _write_ndjson_table(scratch_dir, columns, dtypes, iter(value))
            return {"encoding": "ndjson_path", "path": str(path)}
        return {"encoding": "inline", **_records_to_columnar(value)}

    return value


def _table_to_invoke_form(value: Any) -> Any:
    if isinstance(value, dict) and "encoding" in value:
        if value["encoding"] == "inline":
            columns, dtypes, data = value["columns"], value["dtypes"], value["data"]
        elif value["encoding"] == "ndjson_path":
            columns, dtypes, data = _read_ndjson_table(Path(value["path"]))
        else:
            return value  # an envelope shape this SDK version doesn't know
        try:
            return _columnar_to_dataframe(columns, dtypes, data)
        except ImportError:
            # No pandas installed -- degrade to plain records rather than
            # failing the whole step over an optional extra.
            return _columnar_to_records(columns, data)

    if isinstance(value, list):
        # A plain records list -- an older plugin's output, or a value a
        # workflow/API caller supplied directly. Unchanged from before.
        try:
            import pandas as pd
        except ImportError:
            return value
        return pd.DataFrame(value)

    return value


# -- bytes: wire <-> invoke --------------------------------------------------


def _bytes_to_invoke_form(value: Any) -> Any:
    if isinstance(value, dict):
        return decode_binary(value)
    if isinstance(value, str):
        return base64.b64decode(value)  # older plain-base64-string shape
    return value


# -- public entrypoints -------------------------------------------------------


def to_invoke_form(io_type: str, value: Any, scratch_dir: Path | None = None) -> Any:
    """Convert one value from its wire form to what a plugin's own `invoke()` should see.

    `scratch_dir` is accepted for symmetry with `to_wire_form` but unused
    here -- reading never needs anywhere to write.
    """
    if io_type == "table":
        return _table_to_invoke_form(value)
    if io_type == "bytes":
        return _bytes_to_invoke_form(value)
    return value


def to_wire_form(io_type: str, value: Any, scratch_dir: Path | None = None) -> Any:
    """Convert one plugin-returned value to the canonical, always-JSON-safe wire form.

    `scratch_dir`, when given, is where a value too large to inline gets
    written -- `None` (the default, and always the case for tier BUILTIN,
    which has no scratch-dir lifecycle of its own) means always inline.
    """
    if io_type == "table":
        return _table_to_wire_form(value, scratch_dir)
    if io_type == "bytes" and isinstance(value, (bytes, bytearray)):
        return encode_binary(bytes(value), scratch_dir)
    return value


def convert_inputs(
    specs: "list[IOSpec] | None",
    values: dict[str, Any],
    scratch_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply `to_invoke_form` to every value in `values` whose name has a declared spec in `specs`.

    A name with no matching spec (or `specs` being `None`) passes through
    unconverted, since there's no declared `type` to convert it against.
    """
    if not specs:
        return values
    types_by_name = {spec.name: spec.type for spec in specs}
    return {
        name: to_invoke_form(types_by_name[name], value, scratch_dir=scratch_dir)
        if name in types_by_name
        else value
        for name, value in values.items()
    }


def convert_outputs(
    specs: "list[IOSpec] | None",
    values: dict[str, Any],
    scratch_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply `to_wire_form` to every value in `values` whose name has a declared spec in `specs`.

    A name with no matching spec (or `specs` being `None`) passes through
    unconverted, since there's no declared `type` to convert it against.
    """
    if not specs:
        return values
    types_by_name = {spec.name: spec.type for spec in specs}
    return {
        name: to_wire_form(types_by_name[name], value, scratch_dir=scratch_dir)
        if name in types_by_name
        else value
        for name, value in values.items()
    }
