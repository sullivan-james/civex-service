"""Summaries of record data: group records by field values and work out
measures over each group (how many, how many filled, smallest, largest,
average, total), over exactly the records a `RecordQuery` lists.

Pure: what a summary asks for (`SummaryRequest`), which measures and
groupings a field type allows (read from `FieldTypeDescriptor.measures`,
`.grouping`, `.buckets`, the one table, served by `GET /schemas/field-types`),
what the repository is handed once names are resolved (`GroupPlan`,
`MeasurePlan`) and what comes back (`SummaryResult`). The arithmetic is SQL
(`record_repo.summarise`); the service (`RecordService.summarise`) is the one
place names become ids and raw keys become labelled groups.

Choices worth knowing:

* `count` counts records and needs no field; every other measure is over a
  field's values, and a blank (absent, null, "" or an empty list) is not a
  value: `filled` counts the records that have one.
* There is no median: SQLite has no percentile without an extension, and
  working one out by sorting every value in Python would not be cheap.
* A list field (tags, links to records) groups by each item: a record with
  two tags is in both groups, so the groups' counts can add up to more than
  the total, which counts each record once.
* A date is stored at the precision it was written (2019, 2019-06 or
  2019-06-14). Grouped by a finer period than a value has, it keeps its own
  group ("2019, month not known": `GroupValue.precision`), never guessed into
  one. A week needs a whole date.
* A date and time is grouped by the period in the field's time zone, else
  the collection's, else UTC (`SummaryResult.timezone`).
* A group's `where` is the filter condition that lists exactly its records
  (the explorer drills into a group by adding it to its filter); groups of a
  list field have none, since the filter can't test for one item of a list.
"""

from __future__ import annotations

import calendar
import uuid
import re
from dataclasses import dataclass, field as _field
from datetime import date, datetime, timedelta
from typing import Any

from civex.domain.exceptions import ValidationError
from civex.domain.field_descriptors import FIELD_TYPES

#: Every measure, in the order offered, with its plain name.
MEASURES: dict[str, str] = {
    "count": "Records",
    "filled": "Filled",
    "distinct": "Different values",
    "min": "Smallest",
    "max": "Largest",
    "mean": "Average",
    "sum": "Total",
    "inside": "Records inside",
}
#: What each measure is, in a sentence (the UI's tooltip, the CLI's help).
MEASURE_HELP: dict[str, str] = {
    "count": "How many records.",
    "filled": "How many records have a value in the field.",
    "distinct": "How many different values the field holds.",
    "min": "The smallest value (the earliest date, the first text A to Z).",
    "max": "The largest value (the latest date, the last text A to Z).",
    "mean": "The average of the values.",
    "sum": "The values added up.",
    "inside": "How many records of a kind beneath sit inside them.",
}
#: The measure that counts records of a kind beneath: its `field` names that
#: kind, not a field (`inside:recording`).
INSIDE = "inside"
#: Measures whose answer is a value of the field (so carries its unit).
VALUE_MEASURES = frozenset({"min", "max", "mean", "sum"})
#: Periods a date or date and time can be grouped by.
BUCKETS = ("year", "month", "week", "day")

MAX_GROUP_BY = 3
MAX_MEASURES = 20
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000


@dataclass(frozen=True)
class GroupBy:
    """Group records by a field: of the kind summarised, or of a kind above
    it (`schema`, like a filter condition's)."""

    field: str
    schema: str | None = None
    # date / datetime: a period from BUCKETS (None: each value).
    bucket: str | None = None
    # integer / float: ranges this wide, starting at multiples of it (None:
    # each value).
    bin: float | None = None

    @property
    def key(self) -> str:
        name = f"{self.schema}.{self.field}" if self.schema else self.field
        if self.bucket:
            return f"{name}:{self.bucket}"
        if self.bin is not None:
            return f"{name}:{_number(self.bin)}"
        return name


@dataclass(frozen=True)
class Measure:
    measure: str
    field: str | None = None  # None only for `count`
    schema: str | None = None

    @property
    def key(self) -> str:
        if self.field is None:
            return self.measure
        name = f"{self.schema}.{self.field}" if self.schema else self.field
        return f"{self.measure}:{name}"


@dataclass
class SummaryRequest:
    group_by: list[GroupBy] = _field(default_factory=list)
    measures: list[Measure] = _field(default_factory=lambda: [Measure("count")])
    # The most groups returned; past it the result is `truncated`.
    limit: int = DEFAULT_LIMIT

    def check(self) -> None:
        """The request's own shape: how many, which measures exist."""
        if len(self.group_by) > MAX_GROUP_BY:
            raise ValidationError(f"Group by at most {MAX_GROUP_BY} fields")
        if not self.measures:
            raise ValidationError("Choose at least one thing to work out")
        if len(self.measures) > MAX_MEASURES:
            raise ValidationError(f"Work out at most {MAX_MEASURES} things at once")
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValidationError(f"The limit must be between 1 and {MAX_LIMIT}")
        for m in self.measures:
            if m.measure not in MEASURES:
                raise ValidationError(
                    f"Unknown measure '{m.measure}'. Use one of: " + ", ".join(MEASURES)
                )
            if m.measure == "count" and m.field is not None:
                raise ValidationError(
                    "'count' counts records; to count values, use 'filled'"
                )
            if m.measure == INSIDE and (m.field is None or m.schema):
                raise ValidationError(
                    "'inside' names a kind of record beneath: inside:recording"
                )
            if m.measure != "count" and m.field is None:
                raise ValidationError(f"'{m.measure}' needs a field")
        keys = [g.key for g in self.group_by]
        if len(set(keys)) != len(keys):
            raise ValidationError("A field is grouped by twice the same way")


def measures_for(dtype: str) -> tuple[str, ...]:
    """The measures a field of `dtype` allows (besides `count`)."""
    d = FIELD_TYPES.get(dtype)
    return d.measures if d else ()


def measure_problem(measure: str, dtype: str, name: str) -> str | None:
    if measure in measures_for(dtype):
        return None
    allowed = ", ".join(measures_for(dtype)) or "nothing"
    return f"Can't work out '{measure}' of '{name}' ({dtype}): it allows {allowed}"


def group_problem(group: GroupBy, dtype: str, name: str) -> str | None:
    d = FIELD_TYPES.get(dtype)
    grouping = d.grouping if d else None
    if grouping is None:
        return f"Can't group by '{name}': a {dtype} field has no values to group"
    if group.bucket is not None:
        if grouping != "bucket":
            return f"'{name}' is not a date: it can't be grouped by {group.bucket}"
        assert d is not None
        if group.bucket not in d.buckets:
            return f"Unknown period '{group.bucket}'. Use one of: " + ", ".join(
                d.buckets
            )
    if group.bin is not None:
        if grouping != "bin":
            return f"'{name}' is not a number: it can't be grouped into ranges"
        if not group.bin > 0:
            return "A range's width must be more than 0"
    return None


def parse_group_by(text: str) -> GroupBy:
    """`field`, `schema.field`, then optionally `:period` (a date) or
    `:width` (a number): how the CLI writes a grouping."""
    name, _, how = text.strip().partition(":")
    schema, _, field = name.rpartition(".")
    if not field:
        raise ValidationError(f"'{text}' names no field")
    group = GroupBy(field=field, schema=schema or None)
    if not how:
        return group
    if how in BUCKETS:
        return GroupBy(field, schema or None, bucket=how)
    try:
        return GroupBy(field, schema or None, bin=float(how))
    except ValueError:
        raise ValidationError(
            f"'{how}' is neither a period ({', '.join(BUCKETS)}) nor a range width"
        ) from None


def parse_measure(text: str) -> Measure:
    """`count`, or `measure:field` / `measure:schema.field`."""
    measure, _, name = text.strip().partition(":")
    if not name:
        return Measure(measure)
    schema, _, field = name.rpartition(".")
    return Measure(measure, field, schema or None)


# --- what the repository is handed


@dataclass(frozen=True)
class FieldPlan:
    """A field resolved: its stored key, and where its record sits (0: the
    record summarised, n: the record n levels above it)."""

    field_id: str
    dtype: str
    hops: int = 0


@dataclass(frozen=True)
class GroupPlan:
    field: FieldPlan
    bucket: str | None = None
    bin: float | None = None
    # A date and time's zone: its name (PostgreSQL converts by name) and its
    # offset in minutes then each change as (UTC instant, offset), for
    # SQLite, which has no zones (`timezones.offset_changes`).
    zone: str | None = None
    zone_offsets: tuple[int, tuple[tuple[datetime, int], ...]] | None = None

    @property
    def each(self) -> bool:
        d = FIELD_TYPES.get(self.field.dtype)
        return bool(d and d.grouping == "each")


@dataclass(frozen=True)
class MeasurePlan:
    measure: str
    field: FieldPlan | None = None
    # `inside`: the kind beneath counted (its schema id) and how many levels
    # down its records sit.
    child: tuple[uuid.UUID, int] | None = None


@dataclass
class SummaryPlan:
    groups: list[GroupPlan]
    measures: list[MeasurePlan]
    limit: int


@dataclass
class RawSummary:
    """What the repository answers: each group's keys then its measures, in
    key order (blanks last), at most `limit` of them; the measures over
    every record; whether there were more groups."""

    rows: list[tuple[Any, ...]]
    total: tuple[Any, ...]
    truncated: bool


# --- what comes back


@dataclass
class GroupColumn:
    key: str  # the GroupBy's key
    field: str
    schema: str  # the kind whose field it is
    label: str
    dtype: str
    bucket: str | None = None
    bin: float | None = None
    unit: str | None = None


@dataclass
class MeasureColumn:
    key: str  # the Measure's key
    measure: str
    label: str  # "Average depth"
    field: str | None = None
    schema: str | None = None
    dtype: str | None = None  # the field's (None for count)
    unit: str | None = None


@dataclass
class GroupValue:
    """One group's value for one grouping. `value` is what the records hold
    (a number, text, true/false, a record id, a period's key such as
    "2019-06"); None is the records with no value. `lower`/`upper` bound a
    range or period (upper excluded), so a chart can place it; `precision`
    is set when a date is less precise than the period grouped by."""

    value: Any
    label: str
    lower: Any = None
    upper: Any = None
    precision: str | None = None


@dataclass
class SummaryRow:
    groups: list[GroupValue]
    values: list[Any]
    # The filter tree (wire shape) that lists exactly this group's records,
    # or None when the filter can't say it (an item of a list).
    where: dict[str, Any] | None = None


@dataclass
class SummaryResult:
    schema: str
    group_columns: list[GroupColumn]
    measure_columns: list[MeasureColumn]
    rows: list[SummaryRow]
    # The measures over every record listed (each record once).
    total: list[Any]
    truncated: bool
    limit: int
    # The zone dates and times were grouped in, when any were.
    timezone: str | None = None


def table_of(result: SummaryResult) -> tuple[list[str], list[dict[str, Any]]]:
    """The summary as a table (columns, rows) for `table_files.write_table`:
    a column per grouping (the group's label) and per measure, then a last
    row of totals."""
    columns = [c.label for c in result.group_columns] + [
        m.label + (f" ({m.unit})" if m.unit else "") for m in result.measure_columns
    ]
    width = len(result.group_columns)
    rows = []
    for row in result.rows:
        cells = [g.label for g in row.groups] + list(row.values)
        rows.append(dict(zip(columns, cells)))
    total = (["Total"] + [""] * (width - 1) if width else []) + list(result.total)
    rows.append(dict(zip(columns, total)))
    return columns, rows


# --- labelling keys (pure helpers the service uses)


def _number(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


_KEY = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def period_bounds(key: str, bucket: str | None) -> tuple[str, str, str] | None:
    """(precision, lower, upper) of a date key: the first day of the period
    and the first day after it, as ISO dates. A key of `bucket` "week" with a
    whole date is the week starting that Monday. None for a key that isn't a
    date (a legacy value)."""
    m = _KEY.match(key or "")
    if not m:
        return None
    y = int(m.group(1))
    if m.group(3):
        d = date(y, int(m.group(2)), int(m.group(3)))
        days = 7 if bucket == "week" else 1
        return "day", d.isoformat(), (d + timedelta(days=days)).isoformat()
    if m.group(2):
        mo = int(m.group(2))
        first = date(y, mo, 1)
        last = calendar.monthrange(y, mo)[1]
        return (
            "month",
            first.isoformat()[:7],
            (first + timedelta(days=last)).isoformat()[:7],
        )
    return "year", str(y), str(y + 1)


def precision_label(key: str, precision: str, bucket: str | None) -> str:
    """How a date key reads: itself, or with what isn't known when it is
    less precise than the period grouped by ("2019, month not known")."""
    order = ["year", "month", "day"]
    wanted = "day" if bucket in ("week", "day", None) else bucket
    if bucket is None or order.index(precision) >= order.index(wanted):
        if bucket == "week":
            return f"Week of {key}"
        return key
    missing = {"year": "month", "month": "day"}[precision]
    if bucket == "week":
        missing = "week"
    return f"{key}, {missing} not known"


def _full_date(key: str) -> str:
    """'2019' -> '2019-01-01', '2019-06' -> '2019-06-01'."""
    return key + "-01-01"[: 10 - len(key)] if len(key) < 10 else key


def _leaf(column: GroupColumn, op: str, value: Any = None) -> dict[str, Any]:
    leaf: dict[str, Any] = {"field": column.field, "schema": column.schema, "op": op}
    if op != "is_null":
        leaf["value"] = value
    return leaf


def _between(column: GroupColumn, lower: Any, upper: Any) -> dict[str, Any]:
    return {"and": [_leaf(column, "gte", lower), _leaf(column, "lt", upper)]}


def _as_number(v: Any, dtype: str) -> Any:
    if v is None:
        return None
    if dtype == "integer" and float(v).is_integer():
        return int(v)
    return float(v)


def _with_unit(text: str, unit: str | None) -> str:
    return f"{text} {unit}" if unit else text


def group_value(
    column: GroupColumn,
    key: Any,
    *,
    each: bool = False,
    names: dict[str, str] | None = None,
    to_utc: Any = None,
) -> tuple[GroupValue, dict[str, Any] | None]:
    """One raw group key as a labelled `GroupValue`, with the filter
    condition that lists its records (None when the filter can't say it).
    `names` labels record ids (a link field); `to_utc(local ISO date)` turns
    a period's start in the summary's zone into the stored UTC form, for a
    date and time's condition."""
    dtype = column.dtype
    if key is None:
        if each:
            return GroupValue(None, "No value"), None
        blank = _leaf(column, "is_null")
        if dtype in ("string", "enum", "url"):
            blank = {"or": [blank, _leaf(column, "eq", "")]}
        return GroupValue(None, "No value"), blank
    if each:
        label = (names or {}).get(key, key) if dtype == "reference_list" else key
        return GroupValue(key, str(label)), None
    if dtype in ("integer", "float"):
        n = _as_number(key, dtype)
        if column.bin is None:
            return GroupValue(n, _with_unit(_number(n), column.unit)), _leaf(
                column, "eq", n
            )
        upper = _as_number(float(key) + column.bin, dtype)
        label = _with_unit(f"{_number(n)} to under {_number(upper)}", column.unit)
        return GroupValue(n, label, lower=n, upper=upper), _between(column, n, upper)
    if dtype == "boolean":
        b = key in (True, 1, "true")
        return GroupValue(b, "Yes" if b else "No"), _leaf(column, "eq", b)
    if dtype in ("date", "datetime") and column.bucket is not None:
        bounds = period_bounds(str(key), column.bucket)
        if bounds is None:  # a legacy value that isn't a date
            return GroupValue(key, str(key)), None
        precision, lower, upper = bounds
        label = precision_label(str(key), precision, column.bucket)
        wanted = "day" if column.bucket in ("week", "day") else column.bucket
        coarser = ["year", "month", "day"].index(precision) < [
            "year",
            "month",
            "day",
        ].index(wanted)
        value = GroupValue(
            key,
            label,
            lower=_full_date(lower),
            upper=_full_date(upper),
            precision=precision if coarser else None,
        )
        if dtype == "date":
            if coarser or (column.bucket == "day"):
                return value, _leaf(column, "eq", key)
            return value, _between(column, lower, upper)
        if to_utc is None:
            return value, None
        return value, _between(
            column, to_utc(_full_date(lower)), to_utc(_full_date(upper))
        )
    if dtype == "reference":
        return GroupValue(key, str((names or {}).get(key, key))), _leaf(
            column, "eq", key
        )
    return GroupValue(key, str(key)), _leaf(column, "eq", key)


def measure_value(column: MeasureColumn, v: Any) -> Any:
    """A raw measure as the result carries it: counts as ints, a whole
    number field's smallest, largest and total as ints, averages as floats."""
    if column.measure == INSIDE:
        return int(v or 0)
    if v is None:
        return None
    if column.measure in ("count", "filled", "distinct"):
        return int(v)
    if column.dtype in ("integer", "float"):
        if column.measure == "mean":
            return float(v)
        return _as_number(v, column.dtype)
    return v


#: How a measure column is named, around the field's name.
_MEASURE_NAMES = {
    "filled": "{} filled",
    "distinct": "Different {}",
    "min": "Smallest {}",
    "max": "Largest {}",
    "mean": "Average {}",
    "sum": "Total {}",
}


def measure_label(measure: str, field_label: str | None) -> str:
    if field_label is None:
        return MEASURES[measure]
    return _MEASURE_NAMES[measure].format(field_label)


# --- a chart's summary (`civex.domain.charts.Chart`)

#: How a chart is drawn: `chart` picks from what it groups by (a line over
#: time for dates, bars otherwise); or bars, a line, a pie, or its table of
#: numbers, as chosen.
SHOWS = ("chart", "bars", "line", "pie", "table")
SORT_DIRECTIONS = ("asc", "desc")


@dataclass
class SavedSummary:
    """The bars of a chart: what the records are grouped by and what is
    worked out (the keys `parse_group_by` and `parse_measure` read, as the
    address and the CLI write them), how its table is sorted, whether it
    opens as a table or a chart and which measure the chart draws. Which
    records it counts is not part of it. `from_dict` is the one check of the
    shape; whether the fields exist is the record service's
    (`RecordService.check_summary`)."""

    group_by: list[str] = _field(default_factory=list)
    measures: list[str] = _field(default_factory=lambda: ["count"])
    sort: dict[str, str] | None = None  # {"column": key, "direction": asc|desc}
    show: str = "chart"
    chart_measure: str | None = None

    def request(self) -> SummaryRequest:
        return SummaryRequest(
            group_by=[parse_group_by(g) for g in self.group_by],
            measures=[parse_measure(m) for m in self.measures],
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "group_by": list(self.group_by),
            "measures": list(self.measures),
        }
        if self.sort:
            out["sort"] = dict(self.sort)
        if self.show != "chart":
            out["show"] = self.show
        if self.chart_measure:
            out["chart_measure"] = self.chart_measure
        return out

    @classmethod
    def from_dict(cls, d: Any) -> SavedSummary:
        """Read and check: keys written as the server writes them (so
        `depth:5.0` and `depth:5` are one grouping), a sort on one of its
        columns, a chart measure among its measures."""
        if not isinstance(d, dict):
            raise ValidationError("A chart is an object")
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValidationError("A chart has no " + ", ".join(sorted(unknown)))

        def texts(key: str, default: list[str]) -> list[str]:
            value = d.get(key, default)
            if value is None:
                return list(default)
            if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value
            ):
                raise ValidationError(f"A chart's '{key}' is a list of text")
            return value

        groups = [parse_group_by(g) for g in texts("group_by", [])]
        measures = [parse_measure(m) for m in texts("measures", ["count"])]
        SummaryRequest(group_by=groups, measures=measures).check()
        keys = [g.key for g in groups] + [m.key for m in measures]

        sort = d.get("sort")
        if sort is not None:
            if (
                not isinstance(sort, dict)
                or sort.get("column") not in keys
                or sort.get("direction", "asc") not in SORT_DIRECTIONS
            ):
                raise ValidationError(
                    "A chart is sorted by one of its columns, 'asc' or 'desc'"
                )
            sort = {"column": sort["column"], "direction": sort.get("direction", "asc")}
        show = d.get("show") or "chart"
        if show not in SHOWS:
            raise ValidationError(f"A chart is drawn as one of: {', '.join(SHOWS)}")
        chart = d.get("chart_measure") or None
        if chart is not None and chart not in [m.key for m in measures]:
            raise ValidationError("The chart draws one of its measures")
        return cls(
            group_by=[g.key for g in groups],
            measures=[m.key for m in measures],
            sort=sort,
            show=show,
            chart_measure=chart,
        )
