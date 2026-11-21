"""The SQL behind `RecordRepository.summarise`: one statement that groups the
records a query lists by field values and works out measures over each group,
plus a row over all of them, on SQLite and PostgreSQL alike.

Every value is read through its JSON type first (`json_type` on SQLite,
`jsonb_typeof` on PostgreSQL), so a legacy value of the wrong kind (text in a
number field) is not a number rather than an error, and a blank ("" or an
empty list) is not a value. A field of a record above is read through outer
joins up the parent chain; a list field's items through a lateral
`json_each`/`jsonb_array_elements`. The groups and the total row are one
`UNION ALL`, ordered by the group keys (blanks last), the total first.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Float,
    Integer,
    and_,
    case,
    cast,
    func,
    literal,
    literal_column,
    null,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, TIMESTAMP

from sqlalchemy.orm import aliased

from civex.db.models import Record
from civex.domain.summary import (
    FieldPlan,
    GroupPlan,
    MeasurePlan,
    RawSummary,
    SummaryPlan,
)

PG_TIMESTAMPTZ = TIMESTAMP(timezone=True)

# A date or date and time as it can be read (anything else is no value).
_PG_DATE = "^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$"
_PG_DATETIME = "^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}"
_SQLITE_YEAR = "[0-9][0-9][0-9][0-9]*"


class _Value:
    """One field's value on one record (or alias), read by its JSON type."""

    def __init__(self, entity: Any, field_id: str, pg: bool) -> None:
        self.pg = pg
        if pg:
            self.json = entity.data[field_id]
            self.kind = func.jsonb_typeof(self.json)
            self.raw_text = entity.data[field_id].as_string()
        else:
            path = '$."' + field_id.replace('"', '""') + '"'
            self.kind = func.json_type(entity.data, path)
            self.raw_text = func.json_extract(entity.data, path)
            self.json = None
            self._path = path
            self._data = entity.data

    def is_number(self) -> Any:
        return self.kind == "number" if self.pg else self.kind.in_(["integer", "real"])

    def is_text(self) -> Any:
        return self.kind == ("string" if self.pg else "text")

    def is_array(self) -> Any:
        return self.kind == "array"

    def number(self) -> Any:
        """The value as a float, else NULL (a legacy string never errors)."""
        return case((self.is_number(), cast(self.raw_text, Float)), else_=null())

    def text(self) -> Any:
        """The value when it is non-empty text, else NULL."""
        return case(
            (and_(self.is_text(), self.raw_text != ""), self.raw_text),
            else_=null(),
        )

    def boolean(self) -> Any:
        """'true' / 'false', else NULL."""
        if self.pg:
            return case((self.kind == "boolean", self.raw_text), else_=null())
        return case(
            (self.kind == "true", literal("true")),
            (self.kind == "false", literal("false")),
            else_=null(),
        )

    def array_length(self) -> Any:
        if self.pg:
            return case((self.is_array(), func.jsonb_array_length(self.json)), else_=0)
        return func.json_array_length(self._data, self._path)

    def filled(self) -> Any:
        """Whether the record has a value: anything but absent, null, "" or
        an empty list."""
        bools = ["boolean"] if self.pg else ["true", "false"]
        return or_(
            self.is_number(),
            self.kind.in_(bools + ["object"]),
            and_(self.is_text(), self.raw_text != ""),
            and_(self.is_array(), self.array_length() > 0),
        )


def _floor(x: Any, pg: bool) -> Any:
    if pg:
        return func.floor(x)
    # SQLite's floor() needs its math functions compiled in; CAST truncates
    # toward zero, so step down for a negative non-integer.
    t = cast(x, Integer)
    return t - case((x < t, 1), else_=0)


def _inside(schema_id: Any, depth: int) -> Any:
    """How many live records of a kind `depth` levels beneath sit inside the
    record summarised: a correlated count up the parent chain, so a group's
    total is one SUM in the same statement."""
    lowest = aliased(Record, name="inside_0")
    q = select(func.count(lowest.id)).where(
        lowest.schema_id == schema_id, lowest.deleted_at.is_(None)
    )
    top = lowest
    for level in range(1, depth):
        above = aliased(Record, name=f"inside_{level}")
        q = q.join(above, above.id == top.parent_record_id)
        top = above
    return (
        q.where(top.parent_record_id == Record.id).correlate(Record).scalar_subquery()
    )


class _Compiler:
    def __init__(self, pg: bool) -> None:
        self.pg = pg
        # hops -> alias of the record that many levels above
        self.above: dict[int, Any] = {}
        self.items: list[tuple[Any, Any]] = []  # (table-valued, onclause)

    def entity(self, f: FieldPlan) -> Any:
        if f.hops == 0:
            return Record
        for h in range(1, f.hops + 1):
            if h not in self.above:
                self.above[h] = aliased(Record, name=f"above_{h}")
        return self.above[f.hops]

    def value(self, f: FieldPlan) -> _Value:
        return _Value(self.entity(f), f.field_id, self.pg)

    def joins(self, q: Any) -> Any:
        prev = Record
        for h in sorted(self.above):
            alias = self.above[h]
            q = q.outerjoin(alias, alias.id == prev.parent_record_id)
            prev = alias
        return q

    # --- group keys

    def group_key(self, g: GroupPlan) -> Any:
        f = g.field
        if g.each:
            return self._item(f)
        v = self.value(f)
        if f.dtype in ("integer", "float"):
            n = v.number()
            if g.bin is None:
                return n
            return _floor(n / g.bin, self.pg) * g.bin
        if f.dtype == "boolean":
            return v.boolean()
        if f.dtype == "date":
            return self._date_key(v.text(), g.bucket)
        if f.dtype == "datetime":
            return self._datetime_key(v.text(), g)
        return v.text()

    def _item(self, f: FieldPlan) -> Any:
        """Each text item of a list field, one row per item (a record with
        none keeps one row, with no item)."""
        entity = self.entity(f)
        if self.pg:
            col = entity.data[f.field_id]
            items = case(
                (func.jsonb_typeof(col) == "array", col),
                else_=cast(literal_column("'[]'"), PG_JSONB),
            )
            tv = (
                func.jsonb_array_elements(items)
                .table_valued("value")
                .render_derived(name=f"item_{len(self.items)}")
            )
            key = case(
                (
                    func.jsonb_typeof(tv.c.value) == "string",
                    tv.c.value.op("#>>")(literal_column("'{}'")),
                ),
                else_=null(),
            )
        else:
            path = '$."' + f.field_id.replace('"', '""') + '"'
            arr = case(
                (
                    func.json_type(entity.data, path) == "array",
                    func.json_extract(entity.data, path),
                ),
                else_=literal("[]"),
            )
            tv = (
                func.json_each(arr)
                .table_valued("value", "type")
                .alias(f"item_{len(self.items)}")
            )
            key = case((tv.c.type == "text", tv.c.value), else_=null())
        self.items.append((tv, true()))
        return key

    def _date_key(self, text: Any, bucket: str | None) -> Any:
        """A date's key at `bucket`, or at its own precision when it has less:
        "2019" stays "2019" grouped by month."""
        if self.pg:
            readable = text.op("~")(_PG_DATE)
        else:
            readable = text.op("GLOB")(_SQLITE_YEAR)
        n = func.length(text)
        year = func.substr(text, 1, 4)
        month = func.substr(text, 1, 7)
        day = func.substr(text, 1, 10)
        if bucket is None:
            key = text
        elif bucket == "year":
            key = year
        elif bucket == "month":
            key = case((n >= 7, month), else_=year)
        else:
            whole = day if bucket == "day" else self._week_of(day, is_date=True)
            key = case((n >= 10, whole), (n >= 7, month), else_=year)
        return case((readable, key), else_=null())

    def _week_of(self, day: Any, is_date: bool) -> Any:
        """The Monday starting the week of `day` (a 'YYYY-MM-DD...' text on
        SQLite; a date or timestamp on PostgreSQL), as 'YYYY-MM-DD'."""
        if self.pg:
            when = func.to_date(day, "YYYY-MM-DD") if is_date else day
            return func.to_char(func.date_trunc("week", when), "YYYY-MM-DD")
        return func.date(day, "-6 days", "weekday 1")

    def _datetime_key(self, text: Any, g: GroupPlan) -> Any:
        """The period of a stored UTC instant as wall time in the zone."""
        bucket = g.bucket
        if self.pg:
            readable = text.op("~")(_PG_DATETIME)
            local = func.timezone(g.zone or "UTC", cast(text, PG_TIMESTAMPTZ))
            if bucket is None:
                return case((readable, text), else_=null())
            if bucket == "week":
                key = self._week_of(local, is_date=False)
            else:
                pattern = {"year": "YYYY", "month": "YYYY-MM", "day": "YYYY-MM-DD"}
                key = func.to_char(local, pattern[bucket])
            return case((readable, key), else_=null())
        if bucket is None:
            return text
        utc = func.datetime(text)  # NULL when it can't be read
        local = func.datetime(utc, self._offset(utc, g))
        if bucket == "week":
            return func.date(local, "-6 days", "weekday 1")
        fmt = {"year": "%Y", "month": "%Y-%m", "day": "%Y-%m-%d"}[bucket]
        return func.strftime(fmt, local)

    def _offset(self, utc: Any, g: GroupPlan) -> Any:
        """The zone's offset at `utc` as a SQLite modifier ('+60 minutes'):
        a CASE over the zone's changes, split in halves so a row takes a
        handful of comparisons, not one per change."""
        first, changes = g.zone_offsets or (0, ())

        def mod(minutes: int) -> Any:
            return literal_column(f"'{minutes:+d} minutes'")

        def stamp(i: int) -> Any:
            return literal_column(f"'{changes[i][0]:%Y-%m-%d %H:%M:%S}'")

        def tree(lo: int, hi: int, before: int) -> Any:
            # changes[lo:hi], with offset `before` in force before changes[lo]
            if lo == hi:
                return mod(before)
            if hi - lo == 1:
                return case((utc < stamp(lo), mod(before)), else_=mod(changes[lo][1]))
            mid = (lo + hi) // 2
            left_end = changes[mid - 1][1]
            return case(
                (utc < stamp(mid), tree(lo, mid, before)),
                else_=tree(mid, hi, left_end),
            )

        return tree(0, len(changes), first)

    # --- measures

    def measure(self, m: MeasurePlan, distinct_records: bool) -> Any:
        if m.measure == "count":
            if distinct_records:
                return func.count(func.distinct(Record.id))
            return func.count(Record.id)
        if m.measure == "inside":
            assert m.child is not None
            return func.coalesce(func.sum(_inside(*m.child)), 0)
        assert m.field is not None
        v = self.value(m.field)
        if m.measure == "filled":
            if distinct_records:
                return func.count(func.distinct(case((v.filled(), Record.id))))
            return func.count(case((v.filled(), 1)))
        numeric = m.field.dtype in ("integer", "float")
        if m.field.dtype == "boolean":
            typed = v.boolean()
        else:
            typed = v.number() if numeric else v.text()
        if m.measure == "distinct":
            return func.count(func.distinct(typed))
        if m.measure == "min":
            return func.min(typed)
        if m.measure == "max":
            return func.max(typed)
        if m.measure == "mean":
            return func.avg(typed)
        if m.measure == "sum":
            return func.sum(typed)
        raise ValueError(m.measure)


def summarise(session: Any, base_query: Any, plan: SummaryPlan, pg: bool) -> RawSummary:
    """Run the summary over `base_query`'s records (the explorer's query,
    `_base_query`): one statement."""
    where = base_query.whereclause
    width = len(plan.groups)

    def measures(c: _Compiler, distinct_records: bool) -> list[Any]:
        return [
            c.measure(m, distinct_records).label(f"m{i}")
            for i, m in enumerate(plan.measures)
        ]

    def finish(c: _Compiler, q: Any) -> Any:
        q = c.joins(q.select_from(Record))
        for tv, on in c.items:
            q = q.outerjoin(tv, on)
        return q.where(where) if where is not None else q

    # The total: every record once, whatever the groups.
    tc = _Compiler(pg)
    total_cols = measures(tc, False)
    total = finish(
        tc,
        select(
            literal(1).label("_total"),
            *[null().label(f"k{i}") for i in range(width)],
            *total_cols,
        ),
    )
    if not plan.groups:
        row = session.execute(total).one()
        return RawSummary(rows=[], total=tuple(row[1:]), truncated=False)

    gc = _Compiler(pg)
    keys = [gc.group_key(g).label(f"k{i}") for i, g in enumerate(plan.groups)]
    each = any(g.each for g in plan.groups)
    grouped = finish(
        gc, select(literal(0).label("_total"), *keys, *measures(gc, each))
    ).group_by(*[literal_column(f"k{i}") for i in range(width)])

    both = union_all(total, grouped).subquery("summary")
    order: list[Any] = [both.c._total.desc()]
    for i in range(width):
        k = both.c[f"k{i}"]
        order += [k.is_(None), k]
    rows = session.execute(select(both).order_by(*order).limit(plan.limit + 2)).all()
    total_row = next(r for r in rows if r[0] == 1)
    groups = [tuple(r[1:]) for r in rows if r[0] == 0]
    truncated = len(groups) > plan.limit
    return RawSummary(
        rows=groups[: plan.limit],
        total=tuple(total_row[1 + width :]),
        truncated=truncated,
    )
