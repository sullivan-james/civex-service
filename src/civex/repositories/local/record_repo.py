from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    and_,
    case,
    cast,
    delete,
    false,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
    String,
    type_coerce,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.expression import ClauseElement
from sqlalchemy.orm import Session, aliased

from civex.db.field_values import field_json, field_value
from civex.db import read_scope
from civex.db.models import (
    Dataset,
    Record,
    RecordNote,
    RecordReference,
    Schema,
    WorkflowJob,
)
from civex.domain import notes as note_rules
from civex.domain.dtos import RecordDTO, RestoreRow
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode, SortKey
from civex.domain.file_access import HeldFile
from civex.domain.query import ID_PREFIX_MIN, ResolvedQuery, ResolvedSet, TextSearch
from civex.domain.summary import RawSummary, SummaryPlan
from civex.repositories.local._ids import prefix_span
from civex.repositories.local._bucketing import day_bucket
from civex.repositories.local._jobs import bulk_delete_jobs
from civex.repositories.protocols import RecordGrowthRow, RecordPlace


class _Explain(Executable, ClauseElement):
    """EXPLAIN (FORMAT JSON) of a statement, bound parameters and all."""

    inherit_cache = False

    def __init__(self, stmt: Any) -> None:
        self.stmt = stmt


@compiles(_Explain, "postgresql")
def _compile_explain(element: _Explain, compiler: Any, **kw: Any) -> str:
    return "EXPLAIN (FORMAT JSON) " + compiler.process(element.stmt, **kw)


def _is_unfiltered(query: ResolvedQuery) -> bool:
    return (
        query.dataset_id is None
        and query.schema_id is None
        and query.parent_record_id is None
        and query.within is None
        and query.beneath is None
        and not query.field_filters
        and query.search is None
        and query.filter_tree is None
        and query.created_after is None
        and query.created_before is None
    )


def _sort_terms(sort: list[SortKey] | None) -> list[tuple[Any, bool, bool]]:
    """The sort as (expression, descending, nullable) terms, in order: what a
    view-style sort on JSON fields compares by. Nulls (absent or JSON null)
    always sort last regardless of direction, numeric types compare as
    numbers, everything else (ISO dates/datetimes included) as text. A key on
    an ancestor's field sorts by that ancestor record's value."""
    terms: list[tuple[Any, bool, bool]] = []
    for key in sort or []:
        if key.meta is not None:
            terms.append((_meta_value(key.meta), key.descending, False))
            continue
        kind = "number" if key.numeric else "text"
        if key.rel.direction == "up":
            value = _up_value(key.rel.hops, key.field_id, kind)
        else:
            value = field_value(Record, key.field_id, kind)
        terms.append((value, key.descending, True))
    return terms


def _order_by(sort: list[SortKey] | None) -> list[Any]:
    """ORDER BY terms for `_sort_terms`, each written `<value> ASC|DESC NULLS
    LAST` (nulls last whatever the direction) over `field_value`, so a managed
    field index (`db/field_indexes.py`) can hand rows over in order: SQLite
    and PostgreSQL both walk an index for that form, where the equivalent
    `<value> IS NULL, <value>` made them sort every record."""
    out: list[Any] = []
    for value, descending, nullable in _sort_terms(sort):
        ordered = value.desc() if descending else value.asc()
        out.append(ordered.nulls_last() if nullable else ordered)
    return out


def _after_key(terms: list[tuple[Any, bool, bool]], key: list[Any]) -> Any:
    """WHERE: the row sorts strictly after the row whose term values are
    `key`, under the ordering of `terms` (nulls last, whatever the direction).
    `terms` ends in the non-null (created_at, id) pair, both in the last sort
    key's direction, that makes the ordering total; that pair is one row comparison, which PostgreSQL
    turns into an index range, where the equivalent OR of two branches reads
    from the start of the index and filters."""
    clauses: list[Any] = []
    equal: list[Any] = []
    for (value, descending, nullable), last in zip(terms[:-2], key):
        if last is None:
            # Nulls come last: nothing is after one but a later term.
            after: Any = false()
            same = value.is_(None)
        else:
            beyond = value < last if descending else value > last
            after = or_(beyond, value.is_(None)) if nullable else beyond
            same = value == last
        clauses.append(and_(*equal, after))
        equal.append(same)
    (when, tail_desc, _), (ident, _, _) = terms[-2:]
    here, there = tuple_(when, ident), tuple_(key[-2], key[-1])
    clauses.append(and_(*equal, here < there if tail_desc else here > there))
    return or_(*clauses)


def _meta_value(name: str) -> Any:
    """What a record is sorted by for a `query.META_SORTS` key: its kind's or
    collection's name (a correlated scalar, so no join changes the rows), or
    when it was last changed or made."""
    if name == "@kind":
        return (
            select(func.coalesce(Schema.label, Schema.name))
            .where(Schema.id == Record.schema_id)
            .correlate(Record)
            .scalar_subquery()
        )
    if name == "@collection":
        return (
            select(Dataset.name)
            .where(Dataset.id == Record.dataset_id)
            .correlate(Record)
            .scalar_subquery()
        )
    if name == "@updated_at":
        return Record.updated_at
    return Record.created_at


def _tie_breakers(sort: list[SortKey] | None) -> list[Any]:
    """What orders records the sort leaves equal: oldest first, or newest
    first when the (last) sort key is descending, so a list sorted one way
    is exactly the reverse of the other and a field index
    (`db/field_indexes.py`, whose columns end with these) gives the whole
    order. created_at alone isn't a total order (bulk inserts share
    timestamps), so ties are broken on id -- otherwise OFFSET pages can
    repeat or skip rows."""
    if sort and sort[-1].descending:
        return [Record.created_at.desc(), Record.id.desc()]
    return [Record.created_at, Record.id]


def _chain(columns: Any, hops: int, link: Any):
    """`SELECT columns` over `hops` aliased Records joined in a chain
    (`link(prev, next)` is the join condition), plus the aliases."""
    aliases = [aliased(Record) for _ in range(hops)]
    q = select(columns).select_from(aliases[0])
    for prev, nxt in zip(aliases, aliases[1:]):
        q = q.join(nxt, link(prev, nxt))
    return q, aliases


def _up(prev: Any, nxt: Any) -> Any:
    return nxt.id == prev.parent_record_id


def _down(prev: Any, nxt: Any) -> Any:
    return nxt.parent_record_id == prev.id


def _exists_up(hops: int, predicate):
    """EXISTS an ancestor `hops` levels above the outer Record matching
    `predicate(ancestor_alias)` (a1 is the outer record's parent, each next
    alias the previous one's parent)."""
    q, aliases = _chain(literal(1), hops, _up)
    return (
        q.where(aliases[0].id == Record.parent_record_id, predicate(aliases[-1]))
        .correlate(Record)
        .exists()
    )


def _up_value(hops: int, field_id: str, kind: str):
    """The value of `field_id` on the ancestor `hops` levels above the outer
    Record, as a correlated scalar -- NULL when there is none."""
    aliases = [aliased(Record) for _ in range(hops)]
    value = field_value(aliases[-1], field_id, kind)
    q = select(value).select_from(aliases[0])
    for prev, nxt in zip(aliases, aliases[1:]):
        q = q.join(nxt, _up(prev, nxt))
    return (
        q.where(aliases[0].id == Record.parent_record_id)
        .correlate(Record)
        .scalar_subquery()
    )


def _exists_down(hops: int, schema_id: uuid.UUID | None, predicate):
    """EXISTS a live descendant `hops` levels below the outer Record, of
    `schema_id`, matching `predicate(descendant_alias)`. Every hop follows
    `parent_record_id` (indexed); the terminal schema pins the path."""
    q, aliases = _chain(literal(1), hops, _down)
    last = aliases[-1]
    conds = [aliases[0].parent_record_id == Record.id, last.deleted_at.is_(None)]
    if schema_id is not None:
        conds.append(last.schema_id == schema_id)
    return q.where(*conds, predicate(last)).correlate(Record).exists()


def _canonical(value: Any) -> Any:
    """`value` as find_key_match compares it: numbers as numbers (1 == 1.0),
    and a bool never equal to a number."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _coerce_json_value(v: str) -> Any:
    """Parse v as JSON so JSONB @> containment is type-correct (e.g. "30" → 30)."""
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return v


# Ids per IN (...) -- well under SQLite's bound-variable limit.
_CHUNK = 500


def _chunks(ids: list[uuid.UUID]):
    for start in range(0, len(ids), _CHUNK):
        yield ids[start : start + _CHUNK]


_RESTORE_COLUMNS = (
    Record.id,
    Record.parent_record_id,
    Record.dataset_id,
    Record.schema_id,
    Record.deleted_at,
)

# The ids a bulk statement names at a time: a restore of tens of thousands of
# records is a few dozen statements. SQLite before 3.32 allows 999 variables.
_BULK_CHUNK = 5000
# Unique-key places asked about in one statement.
_KEY_PLACES = 400


def _loose(value: Any) -> Any:
    """A key value as loosely as the database compares it (`find_key_match`
    reads the stored value as the kind of the value asked for, so "7", 7 and
    7.0 meet, and case is not told apart): a key two records may share is
    never missed. A match found this way is a candidate; the caller checks it
    the exact way."""
    if isinstance(value, bool):
        return str(value).lower()
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True).lower()
    return str(value).lower()


def _bulk_size(session: Session) -> int:
    """The ids a bulk statement names at a time (see `_bulk_chunks`)."""
    bind = session.get_bind()
    if bind.dialect.name == "sqlite" and sqlite3.sqlite_version_info < (3, 32):
        return _CHUNK
    return _BULK_CHUNK


def _bulk_chunks(session: Session, ids: list[uuid.UUID]):
    size = _bulk_size(session)
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


# The most a caller limited to some collections is counted to on PostgreSQL
# (`estimate_count`): a count is an exact scan, and the table's statistics
# would count what they may not see.
RESTRICTED_COUNT_CAP = 100_000


class LocalRecordRepository:
    def __init__(self, session: Session, is_postgres: bool = False) -> None:
        self._s = session
        self._pg = is_postgres

    def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> RecordDTO | None:
        q = self._s.query(Record).filter_by(id=id)
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        row = q.first()
        return _to_dto(row) if row else None

    def get_by_prefix(
        self, prefix: str, include_deleted: bool = False
    ) -> RecordDTO | None:
        try:
            uid = uuid.UUID(prefix)
            q = self._s.query(Record).filter(Record.id == uid)
        except ValueError:
            span = prefix_span(prefix)
            if span is None:
                return None
            # A range over the id itself, so the primary-key index serves it;
            # casting the id to text for LIKE would scan every record.
            q = self._s.query(Record).filter(Record.id.between(*span))
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        row = q.first()
        return _to_dto(row) if row else None

    def list_all(self) -> list[RecordDTO]:
        rows = (
            self._s.query(Record)
            .filter(Record.deleted_at.is_(None))
            .order_by(Record.created_at)
            .all()
        )
        return [_to_dto(r) for r in rows]

    def list_deleted(
        self,
        dataset_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[RecordDTO]:
        q = self._s.query(Record).filter(Record.deleted_at.is_not(None))
        if dataset_id is not None:
            q = q.filter(Record.dataset_id == dataset_id)
        q = q.order_by(Record.deleted_at.desc(), Record.id.desc()).offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [_to_dto(r) for r in q.all()]

    def purgeable_deleted(
        self, cutoff: datetime
    ) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
        """(id, collection id, schema id) of the records deleted before `cutoff`
        that can be removed without leaving anything pointing at them: one with a
        child that is staying (live, or deleted since) stays too, and so does
        everything above it."""
        old = and_(Record.deleted_at.is_not(None), Record.deleted_at < cutoff)
        rows = (
            self._s.query(
                Record.id, Record.parent_record_id, Record.dataset_id, Record.schema_id
            )
            .filter(old)
            .all()
        )
        parent_of = {r[0]: r[1] for r in rows}
        # Parents, among these, of a child that is not going.
        staying = {
            pid
            for (pid,) in self._s.query(Record.parent_record_id)
            .filter(
                Record.parent_record_id.in_(select(Record.id).where(old)),
                not_(old),
            )
            .distinct()
        }
        keep: set[uuid.UUID] = set()
        stack = [i for i in staying if i in parent_of]
        while stack:
            rid = stack.pop()
            if rid in keep:
                continue
            keep.add(rid)
            above = parent_of.get(rid)
            if above in parent_of:
                stack.append(above)
        return [(r[0], r[2], r[3]) for r in rows if r[0] not in keep]

    def list_by_dataset(self, dataset_id: uuid.UUID) -> list[RecordDTO]:
        rows = (
            self._s.query(Record)
            .filter_by(dataset_id=dataset_id)
            .filter(Record.deleted_at.is_(None))
            .order_by(Record.created_at)
            .all()
        )
        return [_to_dto(r) for r in rows]

    def list_by_ids(self, ids: list[uuid.UUID]) -> list[RecordDTO]:
        """Batch lookup by id, deleted or not -- a stale reference to a
        since-deleted target should still resolve a display label."""
        if not ids:
            return []
        return [
            _to_dto(r)
            for chunk in _chunks(ids)
            for r in self._s.query(Record).filter(Record.id.in_(chunk)).all()
        ]

    def hidden_referrers(
        self, target_ids: list[uuid.UUID], field_ids: list[uuid.UUID]
    ) -> int:
        """How many records the caller cannot see hold a reference to these
        targets (0 for one who sees everything): what a delete must still
        respect, though it may not say what they are."""
        if not read_scope.restricted(self._s):
            return 0
        seen = {r for r, _, _ in self.referrers_of(target_ids, field_ids)}
        with read_scope.unscoped(self._s):
            every = {r for r, _, _ in self.referrers_of(target_ids, field_ids)}
        return len(every - seen)

    def placement_of(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, RecordPlace]:
        """Where each of these records is (collection, schema and its name,
        whether deleted), deleted ones too, in one query per chunk of ids and
        without loading the records. A record that is not there is left out."""
        found: dict[uuid.UUID, RecordPlace] = {}
        for chunk in _chunks(list(ids)):
            for rid, did, sid, name, gone in (
                self._s.query(
                    Record.id,
                    Record.dataset_id,
                    Record.schema_id,
                    Schema.name,
                    Record.deleted_at,
                )
                .outerjoin(Schema, Schema.id == Record.schema_id)
                .filter(Record.id.in_(chunk))
            ):
                found[rid] = RecordPlace(rid, did, sid, name or "unknown", gone)
        return found

    def any_key_match(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        places: list[tuple[uuid.UUID | None, dict[str, Any]]],
    ) -> bool:
        """Whether a live record of the schema in the collection matches any of
        these (parent, key values): what `find_key_match` asks for each, asked
        for all at once."""
        if not places:
            return False
        options = []
        for parent, key in places:
            parts = [
                Record.parent_record_id.is_(None)
                if parent is None
                else Record.parent_record_id == parent
            ]
            parts += [_typed_comparison(Record, f, "eq", v) for f, v in key.items()]
            options.append(and_(*parts))
        return (
            self._s.query(Record.id)
            .filter(
                Record.dataset_id == dataset_id,
                Record.schema_id == schema_id,
                Record.deleted_at.is_(None),
                or_(*options),
            )
            .first()
            is not None
        )

    def key_clashes(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        places: list[tuple[uuid.UUID | None, dict[str, Any]]],
    ) -> set[int]:
        """Which of these (parent, key values) places a live record of the
        schema in the collection already holds (`any_key_match` for many,
        saying which): a statement per few hundred places, whose matches are
        compared in memory, loosely (a candidate is checked exactly by the
        caller; one the database would call a match is never missed)."""
        hit: set[int] = set()
        # Each place names a parent and, per key field, a path and a value:
        # few enough in a statement to stay under the variable limit.
        widest = max((len(key) for _, key in places), default=1)
        step = max(1, min(_KEY_PLACES, _bulk_size(self._s) // (2 + 3 * widest)))
        for start in range(0, len(places), step):
            part = places[start : start + step]
            options = []
            for parent, key in part:
                parts = [
                    Record.parent_record_id.is_(None)
                    if parent is None
                    else Record.parent_record_id == parent
                ]
                parts += [_typed_comparison(Record, f, "eq", v) for f, v in key.items()]
                options.append(and_(*parts))
            found = self._s.execute(
                select(Record.parent_record_id, Record.data).where(
                    Record.dataset_id == dataset_id,
                    Record.schema_id == schema_id,
                    Record.deleted_at.is_(None),
                    or_(*options),
                )
            ).all()
            if not found:
                continue
            shapes = {tuple(sorted(key)) for _, key in part}
            held = {
                (parent, fields, tuple(_loose((data or {}).get(f)) for f in fields))
                for parent, data in found
                for fields in shapes
            }
            for i, (parent, key) in enumerate(part):
                fields = tuple(sorted(key))
                values = tuple(_loose(key[f]) for f in fields)
                if (parent, fields, values) in held:
                    hit.add(start + i)
        return hit

    def dataset_of(self, id: uuid.UUID) -> uuid.UUID | None:
        """The collection a record is in (deleted ones too), without loading it
        into the session; None when there is no such record."""
        return self._s.query(Record.dataset_id).filter(Record.id == id).scalar()

    def collections_of(self, ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """The collections these records are in: one query per chunk of ids,
        no rows hydrated (what a bulk change asks permission for up front)."""
        found: set[uuid.UUID] = set()
        for chunk in _chunks(ids):
            found.update(
                did
                for (did,) in self._s.query(Record.dataset_id)
                .filter(Record.id.in_(chunk))
                .distinct()
            )
        return found

    def list_filtered(
        self,
        query: ResolvedQuery,
        offset: int,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[RecordDTO]:
        """One page. `after` (the last record of the previous page's
        created_at and id) continues an unsorted listing from there -- keyset
        paging, which costs the same at page 1000 as at page 1, where OFFSET
        walks every row it skips. Only meaningful without a custom sort."""
        q = _base_query(self._s, query, self._pg)
        if after is not None:
            when, last_id = after
            q = q.filter(
                or_(
                    Record.created_at > when,
                    and_(Record.created_at == when, Record.id > last_id),
                )
            )
        q = q.order_by(*_order_by(query.sort), *_tie_breakers(query.sort))
        if offset:
            q = q.offset(offset)
        return [_to_dto(r) for r in q.limit(limit).all()]

    def list_keyset(
        self,
        query: ResolvedQuery,
        limit: int,
        after_key: list[Any] | None = None,
    ) -> tuple[list[RecordDTO], list[Any] | None, str]:
        """One page by keyset, for any sort: (records, key of the last
        record when more follow else None, directions of the key's terms).
        `after_key` is a previous page's key: the page starts strictly after
        that row, so cost doesn't grow with depth and rows added or removed
        meanwhile neither repeat nor skip. created_at and id close the
        ordering, so it is total."""
        # The closing pair follows the last sort key's direction, as
        # `_tie_breakers` does for every other path.
        tail = bool(query.sort and query.sort[-1].descending)
        terms = _sort_terms(query.sort) + [
            (Record.created_at, tail, False),
            (Record.id, tail, False),
        ]
        directions = "".join("d" if d else "a" for _, d, _ in terms)
        q = _base_query(self._s, query, self._pg)
        if after_key is not None:
            if len(after_key) != len(terms):
                raise ValidationError("The cursor does not belong to this query")
            q = q.filter(_after_key(terms, after_key))
        q = q.add_columns(*[t[0].label(f"_k{i}") for i, t in enumerate(terms)])
        q = q.order_by(*_order_by(query.sort), *_tie_breakers(query.sort))
        rows = q.limit(limit + 1).all()
        more = len(rows) > limit
        rows = rows[:limit]
        key = list(rows[-1][1:]) if more else None
        return [_to_dto(r[0]) for r in rows], key, directions

    def count(self, query: ResolvedQuery) -> int:
        return _base_query(self._s, query, self._pg).count()

    def estimate_count(self, query: ResolvedQuery) -> tuple[int, bool]:
        """(how many records `query` lists, whether that is the planner's
        estimate). On PostgreSQL an unfiltered listing reads the table's
        `pg_class.reltuples` and anything else the row estimate of EXPLAIN:
        neither scans a row, so they cost the same at 10 billion records as
        at 10. Deleted rows are counted by `reltuples`, and both are only as
        fresh as the last ANALYZE. Elsewhere the count is exact."""
        if not self._pg:
            return self.count(query), False
        if read_scope.restricted(self._s):
            # The planner's figures are of the whole table, hidden collections
            # included, so they may not be used. An exact count of a big
            # project would scan it, so it stops at RESTRICTED_COUNT_CAP: more
            # than that is reported as the cap, flagged as an estimate.
            capped = (
                _base_query(self._s, query, self._pg)
                .with_entities(Record.id)
                .order_by(None)
                .limit(RESTRICTED_COUNT_CAP + 1)
                .count()
            )
            if capped > RESTRICTED_COUNT_CAP:
                return RESTRICTED_COUNT_CAP, True
            return capped, False
        if _is_unfiltered(query):
            # Summed over the leaf partitions: autovacuum never analyzes the
            # parent of a partitioned table, so its own reltuples is stale or
            # -1. A plain table is its own only leaf. Any never-analyzed leaf
            # (-1) sends this to the planner's estimate below.
            tuples = self._s.execute(
                text(
                    "SELECT CASE WHEN bool_or(c.reltuples < 0) THEN NULL "
                    "ELSE sum(c.reltuples)::bigint END "
                    "FROM pg_partition_tree(to_regclass('records')) t "
                    "JOIN pg_class c ON c.oid = t.relid WHERE t.isleaf"
                )
            ).scalar()
            if tuples is not None:
                return int(tuples), True
        listed = _base_query(self._s, query, self._pg).with_entities(Record.id)
        plan = self._s.execute(_Explain(listed.order_by(None).statement)).scalar()
        assert plan is not None
        return int(plan[0]["Plan"]["Plan Rows"]), True

    def count_open_notes(self, query: ResolvedQuery) -> tuple[int, int]:
        """(threads not yet resolved, records holding them) among the records
        `query` lists: a note and its replies count once. One statement."""
        listed = _base_query(self._s, query, self._pg).with_entities(Record.id)
        notes, records = (
            self._s.query(
                func.count(RecordNote.id),
                func.count(func.distinct(RecordNote.record_id)),
            )
            .filter(
                RecordNote.record_id.in_(listed.scalar_subquery()),
                RecordNote.thread_id.is_(None),
                RecordNote.resolved_at.is_(None),
                RecordNote.deleted_at.is_(None),
            )
            .one()
        )
        return int(notes or 0), int(records or 0)

    def list_ids(self, query: ResolvedQuery) -> list[uuid.UUID]:
        """Ids of every record the query matches -- no rows hydrated, for
        callers (bulk delete) that only need to know which."""
        return [
            rid
            for (rid,) in _base_query(self._s, query, self._pg).with_entities(Record.id)
        ]

    def held_files(
        self,
        picked: ResolvedSet,
        file_fields: dict[str, str],
        search: TextSearch | None = None,
        depth: int = 0,
        following: bool = True,
    ) -> list[HeldFile]:
        """Every file value the set's records hold (see `held_files`)."""
        from civex.repositories.local import held_files

        return held_files.held_files(
            self._s, picked, file_fields, search, depth, self._pg, following
        )

    def holders(self, picked: ResolvedSet) -> list[Any]:
        """The set's records that hold a file (see `held_files.holders`)."""
        from civex.repositories.local import held_files

        return held_files.holders(self._s, picked, self._pg)

    def shared_copies(self) -> dict[tuple[str, str | None], int]:
        """The copies several live records point at, with how many (see
        `held_files.shared_copies`)."""
        from civex.repositories.local import held_files

        return held_files.shared_copies(self._s)

    def count_children(
        self, parent_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, int]]:
        """Live child counts per parent, broken out by child schema name --
        one grouped query for a whole page of parents."""
        if not parent_ids:
            return {}
        rows = (
            self._s.query(Record.parent_record_id, Schema.name, func.count(Record.id))
            .join(Schema, Record.schema_id == Schema.id)
            .filter(
                Record.parent_record_id.in_(parent_ids), Record.deleted_at.is_(None)
            )
            .group_by(Record.parent_record_id, Schema.name)
            .all()
        )
        counts: dict[uuid.UUID, dict[str, int]] = {}
        for parent_id, schema_name, n in rows:
            if parent_id is None:  # never: the query asks for these parents
                continue
            counts.setdefault(parent_id, {})[schema_name] = n
        return counts

    def _by_schema_query(self, schema_id: uuid.UUID, search: TextSearch | None):
        q = self._s.query(Record).filter(
            Record.schema_id == schema_id, Record.deleted_at.is_(None)
        )
        if search:
            q = q.filter(text_match(search, self._pg))
        return q

    def list_by_schema(
        self,
        schema_id: uuid.UUID,
        search: TextSearch | None = None,
        limit: int = 20,
        dataset_ids: list[uuid.UUID] | None = None,
    ) -> list[RecordDTO]:
        q = self._by_schema_query(schema_id, search)
        if dataset_ids is not None:
            q = q.filter(Record.dataset_id.in_(dataset_ids))
        rows = q.order_by(Record.created_at.desc(), Record.id.desc()).limit(limit).all()
        return [_to_dto(r) for r in rows]

    def search_all(
        self,
        search: TextSearch,
        limit: int = 20,
        dataset_id: uuid.UUID | None = None,
    ) -> list[RecordDTO]:
        """Live records of any schema matching `search`, best match first.

        One query across every schema (and, unless `dataset_id` narrows it,
        every collection). Records whose collection or schema is soft-deleted
        are left out, even though the record row itself may not be marked.
        The match is `text_match`, the explorer's; on PostgreSQL results are
        ranked by full-text relevance, elsewhere (and among equals) newest
        first."""
        q = (
            self._s.query(Record)
            .join(Dataset, Record.dataset_id == Dataset.id)
            .join(Schema, Record.schema_id == Schema.id)
            .filter(
                Record.deleted_at.is_(None),
                Dataset.deleted_at.is_(None),
                Schema.deleted_at.is_(None),
            )
        )
        if dataset_id is not None:
            q = q.filter(Record.dataset_id == dataset_id)
        q = q.filter(text_match(search, self._pg))
        newest: list[Any] = [Record.created_at.desc(), Record.id.desc()]
        if self._pg:
            tsquery = func.plainto_tsquery("simple", search.term)
            q = q.order_by(func.ts_rank(Record.search_vector, tsquery).desc(), *newest)
        else:
            q = q.order_by(*newest)
        return [_to_dto(r) for r in q.limit(limit).all()]

    def count_schema_matches(
        self, schema_id: uuid.UUID, search: TextSearch | None = None
    ) -> int:
        """Same predicate as list_by_schema, so a count and a page agree."""
        return self._by_schema_query(schema_id, search).count()

    def count_by_schema_ids(self, schema_ids: list[uuid.UUID]) -> int:
        """Records (deleted or not) typed by any of `schema_ids`."""
        if not schema_ids:
            return 0
        return (
            self._s.query(func.count(Record.id))
            .filter(Record.schema_id.in_(schema_ids))
            .scalar()
            or 0
        )

    def list_children(
        self, parent_id: uuid.UUID, include_deleted: bool = False
    ) -> list[RecordDTO]:
        q = self._s.query(Record).filter_by(parent_record_id=parent_id)
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        return [_to_dto(r) for r in q.all()]

    def list_children_of(self, parent_ids: list[uuid.UUID]) -> list[RecordDTO]:
        """The live direct children of all of these records, in a query per chunk
        of ids (an index lookup on parent), not one per record."""
        return [
            _to_dto(r)
            for chunk in _chunks(parent_ids)
            for r in self._s.query(Record)
            .filter(Record.parent_record_id.in_(chunk), Record.deleted_at.is_(None))
            .all()
        ]

    def referrers_of(
        self, target_ids: list[uuid.UUID], field_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
        """(referrer id, field id, target id) for every live record holding a
        value in one of `field_ids` that points at any of `target_ids` -- an
        index lookup in record_references, not a search of record data."""
        if not target_ids or not field_ids:
            return []
        rr = RecordReference
        # Two steps, not a JOIN to records: written as a join the planner
        # (SQLite, measured) drives from "every live record" and probes
        # record_references per row -- a scan of the whole table per call --
        # instead of starting from the indexed target.
        found = [
            (row[0], row[1], row[2])
            for chunk in _chunks(list(target_ids))
            for row in self._s.execute(
                select(rr.record_id, rr.field_id, rr.target_id).where(
                    rr.target_id.in_(chunk), rr.field_id.in_(field_ids)
                )
            )
        ]
        live: set[uuid.UUID] = set()
        for chunk in _chunks(list({row[0] for row in found})):
            live.update(
                self._s.scalars(
                    select(Record.id).where(
                        Record.id.in_(chunk), Record.deleted_at.is_(None)
                    )
                )
            )
        return [row for row in found if row[0] in live]

    def referrer_groups(
        self, target_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, str, uuid.UUID, int]]:
        """Who points at `target_id`, counted per (collection, schema name,
        field): live referrers only."""
        if not field_ids:
            return []
        rr = RecordReference
        rows = self._s.execute(
            select(Record.dataset_id, Schema.name, rr.field_id, func.count())
            .select_from(rr)
            .join(Record, Record.id == rr.record_id)
            .join(Schema, Schema.id == Record.schema_id)
            .where(
                rr.target_id == target_id,
                rr.field_id.in_(field_ids),
                Record.deleted_at.is_(None),
            )
            .group_by(Record.dataset_id, Schema.name, rr.field_id)
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def referrers_into_dataset(
        self, dataset_id: uuid.UUID, field_ids: list[uuid.UUID], limit: int
    ) -> tuple[int, list[tuple[uuid.UUID, uuid.UUID]]]:
        """Live records in *other* collections that point at a live record in
        `dataset_id`: how many there are, and (record id, field id) pairs for
        the first `limit` of them."""
        if not field_ids:
            return 0, []
        rr = RecordReference
        # The tables, not aliased ORM entities: the read-scope criteria would
        # rewrite an aliased entity's join condition into invalid SQL. The scope
        # still holds, through `rr` (a reference of a hidden record is absent).
        target, referrer = Record.__table__.alias(), Record.__table__.alias()
        where = (
            target.c.dataset_id == dataset_id,
            target.c.deleted_at.is_(None),
            referrer.c.dataset_id != dataset_id,
            referrer.c.deleted_at.is_(None),
            rr.field_id.in_(field_ids),
        )

        def joined(*cols):
            return (
                select(*cols)
                .select_from(rr)
                .join(referrer, referrer.c.id == rr.record_id)
                .join(target, target.c.id == rr.target_id)
                .where(*where)
            )

        total = self._s.scalar(joined(func.count(func.distinct(rr.record_id)))) or 0
        page = list(
            self._s.scalars(
                joined(rr.record_id).distinct().order_by(rr.record_id).limit(limit)
            )
        )
        if not page:
            return total, []
        pairs = self._s.execute(
            joined(rr.record_id, rr.field_id).where(rr.record_id.in_(page))
        )
        return total, [(r[0], r[1]) for r in pairs]

    def referrer_collections_into_dataset(
        self, dataset_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not field_ids:
            return set()
        rr = RecordReference
        target, referrer = Record.__table__.alias(), Record.__table__.alias()
        return set(
            self._s.scalars(
                select(referrer.c.dataset_id)
                .select_from(rr)
                .join(referrer, referrer.c.id == rr.record_id)
                .join(target, target.c.id == rr.target_id)
                .where(
                    target.c.dataset_id == dataset_id,
                    target.c.deleted_at.is_(None),
                    referrer.c.dataset_id != dataset_id,
                    referrer.c.deleted_at.is_(None),
                    rr.field_id.in_(field_ids),
                )
                .distinct()
            )
        )

    def hidden_referrers_into_dataset(
        self, dataset_id: uuid.UUID, field_ids: list[uuid.UUID]
    ) -> int:
        """How many records the caller cannot see, in other collections, point
        at a live record in `dataset_id` (0 for one who sees everything): what
        deleting or localising that collection must still respect."""
        if not read_scope.restricted(self._s):
            return 0
        seen, _ = self.referrers_into_dataset(dataset_id, field_ids, 0)
        with read_scope.unscoped(self._s):
            every, _ = self.referrers_into_dataset(dataset_id, field_ids, 0)
        return max(every - seen, 0)

    def dangling_references(
        self, field_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, str, uuid.UUID, uuid.UUID]]:
        """(record id, its schema name, field id, target id) for every live
        record whose value in one of `field_ids` names no live record."""
        if not field_ids:
            return []
        rr = RecordReference
        target = aliased(Record)
        rows = self._s.execute(
            select(rr.record_id, Schema.name, rr.field_id, rr.target_id)
            .select_from(rr)
            .join(Record, Record.id == rr.record_id)
            .join(Schema, Schema.id == Record.schema_id)
            .outerjoin(
                target, and_(target.id == rr.target_id, target.deleted_at.is_(None))
            )
            .where(
                Record.deleted_at.is_(None),
                rr.field_id.in_(field_ids),
                target.id.is_(None),
            )
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def count_by_schema(self, query: ResolvedQuery) -> dict[str, int]:
        rows = (
            _base_query(self._s, query, self._pg)
            .with_entities(Schema.name, func.count(Record.id))
            .join(Schema, Record.schema_id == Schema.id)
            .group_by(Schema.name)
            .all()
        )
        return {name: count for name, count in rows}

    def summarise(self, query: ResolvedQuery, plan: SummaryPlan) -> RawSummary:
        """Group the records `query` lists by field values and work out the
        plan's measures over each group and over them all: one statement
        (`summary_sql`)."""
        from civex.repositories.local import summary_sql

        return summary_sql.summarise(
            self._s, _base_query(self._s, query, self._pg), plan, self._pg
        )

    def geometries(
        self, query: ResolvedQuery, field_id: str, hops: int, limit: int
    ) -> tuple[list[tuple[RecordDTO, Any]], int]:
        """The records `query` lists that have a geometry (a JSON object) in
        `field_id`, on the record itself (`hops` 0) or on the record that
        many levels above it: at most `limit`, oldest first, each with the
        geometry, plus how many there are in all. Two statements."""
        from civex.repositories.local.summary_sql import _Value

        owner: Any = Record
        q = _base_query(self._s, query, self._pg)
        prev: Any = Record
        for h in range(1, hops + 1):
            owner = aliased(Record, name=f"geo_above_{h}")
            q = q.join(owner, owner.id == prev.parent_record_id)
            prev = owner
        value = _Value(owner, field_id, self._pg)
        has = value.kind == "object"
        total = q.filter(has).with_entities(func.count(Record.id)).scalar() or 0
        rows = (
            q.filter(has)
            .with_entities(Record, value.raw_text)
            .order_by(Record.created_at, Record.id)
            .limit(limit)
            .all()
        )
        out: list[tuple[RecordDTO, Any]] = []
        for row, raw in rows:
            geometry = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(geometry, dict):
                out.append((_to_dto(row), geometry))
        return out, int(total)

    def growth_by_period(
        self,
        dataset_id: uuid.UUID | None,
        schema_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
    ) -> list[RecordGrowthRow]:
        """Record creation counts per day, broken out by dataset and schema
        name -- the raw series backing the record-growth-over-time widget.
        Scoping by `dataset_id` (as the analytics endpoint's `dataset` filter
        does) lets this use `ix_records_dataset_created`; an unscoped,
        wide-open-ended call falls back to a plain `created_at` scan."""
        day = day_bucket(Record.created_at)
        q = (
            self._s.query(day, Dataset.name, Schema.name, func.count(Record.id))
            .join(Dataset, Record.dataset_id == Dataset.id)
            .join(Schema, Record.schema_id == Schema.id)
            .filter(Record.deleted_at.is_(None))
        )
        if dataset_id is not None:
            q = q.filter(Record.dataset_id == dataset_id)
        if schema_id is not None:
            q = q.filter(Record.schema_id == schema_id)
        if start is not None:
            q = q.filter(Record.created_at >= start)
        if end is not None:
            q = q.filter(Record.created_at < end)
        rows = q.group_by(day, Dataset.name, Schema.name).order_by(day).all()
        return [
            (d, dataset_name, schema_name, count)
            for d, dataset_name, schema_name, count in rows
        ]

    def create(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        data: dict[str, Any],
        parent_record_id: uuid.UUID | None = None,
        id: uuid.UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> RecordDTO:
        # search_vector is maintained by a Postgres trigger (CIVEX-173) so it
        # can't go stale on writes that don't go through this repo; unused on
        # SQLite (see models._TSVECTOR).
        # `id` and the dates are given when a record is brought in from another
        # project (a bundle), so its parent and references still mean the same.
        given = {
            k: v
            for k, v in (
                ("id", id),
                ("created_at", created_at),
                ("updated_at", updated_at),
            )
            if v is not None
        }
        row = Record(
            dataset_id=dataset_id,
            schema_id=schema_id,
            data=data,
            parent_record_id=parent_record_id,
            **given,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def update(self, id: uuid.UUID, data: dict[str, Any]) -> RecordDTO:
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Record '{id}' not found")
        row.data = data
        self._s.flush()
        return _to_dto(row)

    def update_many(
        self, rows: list[tuple[uuid.UUID, dict[str, Any]]], stamp: datetime
    ) -> None:
        """Save many records' data at once, each changed at `stamp`: one
        statement for the lot (the driver runs it once per row), where
        `update` is a read and a write per record. For changes that leave
        every file and every link to another record as it was: the catalogs
        kept in step by a single save's events (`file_references`,
        `record_references`) are not touched here."""
        if not rows:
            return
        self._s.execute(
            update(Record),
            [{"id": rid, "data": data, "updated_at": stamp} for rid, data in rows],
        )
        # Copies of these records the session holds are out of date now.
        changed = {rid for rid, _ in rows}
        for held in list(self._s.identity_map.values()):
            if isinstance(held, Record) and held.id in changed:
                self._s.expire(held)

    def field_rows(
        self,
        field_ids: list[str],
        query: ResolvedQuery | None = None,
        ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[Any, Any, Any, dict[str, Any]]]:
        """For every live record `query` lists (or among `ids`): its id, its
        schema and its collection (each as the database keeps it) and its
        values for `field_ids` alone (those it has). What a plan of an edit to
        those fields has to read of each record, in one statement however
        many (a few, for a great many ids), instead of the records."""
        columns = [
            type_coerce(Record.id, String),
            type_coerce(Record.schema_id, String),
            type_coerce(Record.dataset_id, String),
            *[_field_value(f, self._pg) for f in field_ids],
        ]
        if query is not None:
            batches = [_base_query(self._s, query, self._pg).with_entities(*columns)]
        else:
            wanted = list(ids or [])
            batches = [
                self._s.query(*columns).filter(
                    Record.id.in_(wanted[i : i + _MANY_IDS]),
                    Record.deleted_at.is_(None),
                )
                for i in range(0, len(wanted), _MANY_IDS)
            ]
        out: list[tuple[Any, Any, Any, dict[str, Any]]] = []
        for batch in batches:
            for rid, schema_id, dataset_id, *values in batch:
                held = {}
                for field_id, value in zip(field_ids, values):
                    value = _loaded(value, self._pg)
                    if value is not None:
                        held[field_id] = value
                out.append((rid, schema_id, dataset_id, held))
        return out

    def open_notes_of(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, str]]:
        """For each of these records with threads of notes not yet resolved:
        how many, and the text of the latest one's first note (records with
        none are left out). One query per chunk, whatever the number of
        notes: the count and the latest come from one windowed pass."""
        out: dict[uuid.UUID, tuple[int, str]] = {}
        for chunk in _chunks(ids):
            ranked = (
                select(
                    RecordNote.record_id.label("record_id"),
                    RecordNote.body.label("body"),
                    func.count().over(partition_by=RecordNote.record_id).label("open"),
                    func.row_number()
                    .over(
                        partition_by=RecordNote.record_id,
                        order_by=(RecordNote.created_at.desc(), RecordNote.id.desc()),
                    )
                    .label("nth"),
                )
                .where(
                    RecordNote.record_id.in_(chunk),
                    RecordNote.thread_id.is_(None),
                    RecordNote.resolved_at.is_(None),
                    RecordNote.deleted_at.is_(None),
                )
                .subquery()
            )
            for rid, body, n in self._s.execute(
                select(ranked.c.record_id, ranked.c.body, ranked.c.open).where(
                    ranked.c.nth == 1
                )
            ):
                out[rid] = (int(n), body)
        return out

    def find_key_match(
        self,
        dataset_id: uuid.UUID,
        schema_id: uuid.UUID,
        parent_record_id: uuid.UUID | None,
        key: dict[str, Any],
        exclude_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> RecordDTO | None:
        """A record of the schema, in the same place (collection and parent),
        holding exactly `key`'s values (field id -> scalar). Live ones only
        unless `include_deleted`; `exclude_id` leaves out the record being
        saved."""
        q = self._s.query(Record).filter(
            Record.dataset_id == dataset_id, Record.schema_id == schema_id
        )
        if not include_deleted:
            q = q.filter(Record.deleted_at.is_(None))
        if parent_record_id is None:
            q = q.filter(Record.parent_record_id.is_(None))
        else:
            q = q.filter(Record.parent_record_id == parent_record_id)
        if exclude_id is not None:
            q = q.filter(Record.id != exclude_id)
        for field_id, value in key.items():
            q = q.filter(_typed_comparison(Record, field_id, "eq", value))
        row = q.order_by(Record.created_at).first()
        return _to_dto(row) if row else None

    def deleted_states(
        self,
        *,
        schema_id: uuid.UUID | None = None,
        dataset_id: uuid.UUID | None = None,
    ) -> dict[uuid.UUID, datetime | None]:
        """When each record of a schema or a collection was deleted (None for a
        live one): what a schema's or collection's delete or restore changes."""
        q = select(Record.id, Record.deleted_at)
        if schema_id is not None:
            q = q.where(Record.schema_id == schema_id)
        if dataset_id is not None:
            q = q.where(Record.dataset_id == dataset_id)
        return {rid: at for rid, at in self._s.execute(q)}

    def live_schema_ids(self, dataset_id: uuid.UUID) -> set[uuid.UUID]:
        """The schemas of the live records in a collection."""
        return {
            sid
            for (sid,) in self._s.execute(
                select(Record.schema_id)
                .where(Record.dataset_id == dataset_id, Record.deleted_at.is_(None))
                .distinct()
            )
        }

    def key_duplicates(
        self, schema_id: uuid.UUID, field_ids: list[str]
    ) -> list[list[uuid.UUID]]:
        """Groups of live records of the schema that already share `field_ids`'
        values in the same place (collection and parent): each group is the ids
        of two or more records. Records with a blank in the key are skipped."""
        from civex.domain.uniqueness import key_values

        groups: dict[tuple, list[uuid.UUID]] = {}
        rows = self._s.execute(
            select(Record.id, Record.dataset_id, Record.parent_record_id, Record.data)
            .where(Record.schema_id == schema_id, Record.deleted_at.is_(None))
            .order_by(Record.created_at)
        ).yield_per(1000)
        for rid, dataset_id, parent_id, data in rows:
            values = key_values(data or {}, field_ids)
            if values is None:
                continue
            marker = (dataset_id, parent_id, tuple(_canonical(v) for v in values))
            groups.setdefault(marker, []).append(rid)
        return [ids for ids in groups.values() if len(ids) > 1]

    def has_key_duplicate(self, schema_id: uuid.UUID, field_ids: list[str]) -> bool:
        """Whether `key_duplicates` would find any group: the database narrows
        the records to those that share what the key holds (a window count,
        so nothing else is read), and the first group confirmed ends it. The
        database's equality is never narrower than ours (a number is a number
        however written), so it can only name more candidates, which are then
        judged exactly as `key_duplicates` does."""
        from civex.domain.uniqueness import key_values

        if not field_ids:
            return False
        values = [field_json(Record, f) for f in field_ids]
        sharing = func.count().over(
            partition_by=[Record.dataset_id, Record.parent_record_id, *values]
        )
        inner = (
            select(
                Record.dataset_id.label("d"),
                Record.parent_record_id.label("p"),
                Record.data.label("v"),
                sharing.label("n"),
            )
            .where(
                Record.schema_id == schema_id,
                Record.deleted_at.is_(None),
                *[v.is_not(None) for v in values],
            )
            .subquery()
        )
        seen: set[tuple] = set()
        rows = self._s.execute(
            select(inner.c.d, inner.c.p, inner.c.v).where(inner.c.n > 1)
        ).yield_per(1000)
        try:
            for dataset_id, parent_id, data in rows:
                found = key_values(data or {}, field_ids)
                if found is None:
                    continue
                marker = (dataset_id, parent_id, tuple(_canonical(v) for v in found))
                if marker in seen:
                    return True
                seen.add(marker)
        finally:
            rows.close()
        return False

    def subtree_levels(
        self, root_ids: list[uuid.UUID], deleted: bool | None = None
    ) -> list[list[uuid.UUID]]:
        """The records under `root_ids`, a level at a time: level 0 is the
        roots that exist (and match `deleted`), level 1 their children, and so
        on -- one query per level however many records are in it.

        `deleted`: False follows live records only, True deleted ones only,
        None either. A record appearing at a deeper level than 0 is also a
        descendant of another root."""

        def matching(*extra):
            q = select(Record.id).where(*extra)
            if deleted is True:
                q = q.where(Record.deleted_at.is_not(None))
            elif deleted is False:
                q = q.where(Record.deleted_at.is_(None))
            return q

        levels: list[list[uuid.UUID]] = []
        frontier = [
            rid
            for chunk in _chunks(list(dict.fromkeys(root_ids)))
            for rid in self._s.scalars(matching(Record.id.in_(chunk)))
        ]
        seen: set[uuid.UUID] = set()
        while frontier:
            levels.append(frontier)
            seen.update(frontier)
            frontier = [
                rid
                for chunk in _chunks(frontier)
                for rid in self._s.scalars(matching(Record.parent_record_id.in_(chunk)))
                if rid not in seen
            ]
        return levels

    def delete_many(self, ids: list[uuid.UUID], stamp: datetime | None = None) -> None:
        """Soft-delete every live record in `ids`. Not an edit: each keeps the
        date it was last changed."""
        now = stamp or datetime.now(timezone.utc)
        for chunk in _chunks(ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk), Record.deleted_at.is_(None))
                .values(deleted_at=now, updated_at=Record.updated_at)
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def references_of(
        self, record_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
        rr = RecordReference
        return [
            (row[0], row[1], row[2])
            for chunk in _chunks(list(record_ids))
            for row in self._s.execute(
                select(rr.record_id, rr.field_id, rr.target_id).where(
                    rr.record_id.in_(chunk)
                )
            )
        ]

    def dataset_mismatches(self, record_ids: list[uuid.UUID]) -> int:
        parent = aliased(Record)
        total = 0
        for chunk in _chunks(list(record_ids)):
            total += (
                self._s.scalar(
                    select(func.count(Record.id))
                    .join(parent, parent.id == Record.parent_record_id)
                    .where(
                        or_(Record.id.in_(chunk), Record.parent_record_id.in_(chunk)),
                        Record.dataset_id != parent.dataset_id,
                    )
                )
                or 0
            )
        return total

    def move(
        self,
        ids: list[uuid.UUID],
        dataset_id: uuid.UUID,
        root_ids: list[uuid.UUID],
        parent_id: uuid.UUID | None,
        stamp: datetime,
    ) -> None:
        """A bulk UPDATE per chunk. Between statements a child may sit in
        another collection than its parent: the key that forbids it is checked
        when the transaction commits (`fk_records_parent_same_dataset`)."""
        for chunk in _chunks(list(ids)):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(dataset_id=dataset_id, updated_at=stamp)
                .execution_options(synchronize_session=False)
            )
        for chunk in _chunks(list(root_ids)):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(parent_record_id=parent_id, updated_at=stamp)
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def live_under_deleted(self, limit: int) -> tuple[list[RecordDTO], int]:
        """Live records whose parent record is deleted, oldest change first, at
        most `limit`, and how many there are. Such a record is out of sight:
        nothing above it lists it."""
        parent = aliased(Record)
        base = (
            self._s.query(Record)
            .join(parent, parent.id == Record.parent_record_id)
            .filter(Record.deleted_at.is_(None), parent.deleted_at.is_not(None))
        )
        total = base.count()
        rows = base.order_by(Record.updated_at, Record.id).limit(limit).all()
        return [_to_dto(r) for r in rows], total

    def recently_changed(self, schema_id: uuid.UUID, limit: int) -> list[str]:
        """Ids of the live records of exactly this schema, the most recently
        changed first, at most `limit`."""
        rows = (
            self._s.query(Record.id)
            .filter(Record.schema_id == schema_id, Record.deleted_at.is_(None))
            .order_by(Record.updated_at.desc(), Record.id)
            .limit(limit)
            .all()
        )
        return [str(r.id) for r in rows]

    def restore_rows(
        self, ids: list[uuid.UUID], deleted_only: bool = False
    ) -> list[RestoreRow]:
        """The columns a restore is decided from, for these records (those that
        exist; only the deleted ones with `deleted_only`): a statement per
        chunk of `_bulk_chunk`, and no values loaded."""
        out: list[RestoreRow] = []
        for chunk in _bulk_chunks(self._s, list(dict.fromkeys(ids))):
            q = select(*_RESTORE_COLUMNS).where(Record.id.in_(chunk))
            if deleted_only:
                q = q.where(Record.deleted_at.is_not(None))
            out.extend(RestoreRow(*row) for row in self._s.execute(q))
        return out

    def parent_links(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID | None]:
        """Each of these records' parent (None at the top), deleted or not: two
        columns, a statement per chunk."""
        return {
            rid: parent
            for chunk in _bulk_chunks(self._s, list(dict.fromkeys(ids)))
            for rid, parent in self._s.execute(
                select(Record.id, Record.parent_record_id).where(Record.id.in_(chunk))
            )
        }

    def deleted_at_of(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime | None]:
        """When each of these records that exists was deleted (None for a live
        one): two columns, a statement per chunk."""
        return {
            rid: at
            for chunk in _bulk_chunks(self._s, list(dict.fromkeys(ids)))
            for rid, at in self._s.execute(
                select(Record.id, Record.deleted_at).where(Record.id.in_(chunk))
            )
        }

    def count_deleted_with(self, parent_ids: list[uuid.UUID]) -> int:
        """How many records sit directly under these and were deleted with them
        (`deleted_with`), counted in the database: no rows come back."""
        above = aliased(Record)
        return sum(
            self._s.scalar(
                select(func.count(Record.id))
                .join(above, above.id == Record.parent_record_id)
                .where(
                    Record.parent_record_id.in_(chunk),
                    Record.deleted_at.is_not(None),
                    Record.deleted_at == above.deleted_at,
                )
            )
            or 0
            for chunk in _bulk_chunks(self._s, parent_ids)
        )

    def deleted_with(
        self, parent_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """(id, parent id) of the records directly under these that were deleted
        with them: deleted, with the very stamp the parent carries."""
        above = aliased(Record)
        out: list[tuple[uuid.UUID, uuid.UUID]] = []
        for chunk in _bulk_chunks(self._s, parent_ids):
            q = (
                select(Record.id, Record.parent_record_id)
                .join(above, above.id == Record.parent_record_id)
                .where(
                    Record.parent_record_id.in_(chunk),
                    Record.deleted_at.is_not(None),
                    Record.deleted_at == above.deleted_at,
                )
            )
            out.extend((rid, pid) for rid, pid in self._s.execute(q) if pid is not None)
        return out

    def restore_many(self, ids: list[uuid.UUID]) -> None:
        for chunk in _bulk_chunks(self._s, ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(deleted_at=None, updated_at=Record.updated_at)
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def purge_many(self, ids: list[uuid.UUID]) -> None:
        """Permanently remove records and their workflow jobs. Parent links
        among `ids` are cleared first, so the order they go in can't trip the
        self-referencing foreign key."""
        for chunk in _chunks(ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(parent_record_id=None)
                .execution_options(synchronize_session=False)
            )
        for chunk in _chunks(ids):
            bulk_delete_jobs(self._s, WorkflowJob.record_id.in_(chunk))
            self._s.execute(
                delete(Record)
                .where(Record.id.in_(chunk))
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def delete(self, id: uuid.UUID) -> None:
        row = self._s.query(Record).filter_by(id=id).first()
        if row and row.deleted_at is None:
            row.deleted_at = datetime.now(timezone.utc)
            self._s.flush()

    def restore(self, id: uuid.UUID) -> RecordDTO:
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            raise NotFoundError(f"Record '{id}' not found")
        row.deleted_at = None
        self._s.flush()
        return _to_dto(row)

    def purge(self, id: uuid.UUID) -> None:
        """Permanently remove a single (already soft-deleted) record and its
        workflow jobs. Descendant purging is the caller's job (RecordService
        mirrors the recursion it already does for delete())."""
        row = self._s.query(Record).filter_by(id=id).first()
        if row is None:
            return
        bulk_delete_jobs(self._s, WorkflowJob.record_id == id)
        self._s.delete(row)
        self._s.flush()


# Ids named in one statement (well inside SQLite's and PostgreSQL's limits
# on bound values).
_MANY_IDS = 20_000


def _field_value(field_id: str, pg: bool) -> Any:
    """A record's value for one field, read alone: parsed on PostgreSQL, and
    as JSON text on SQLite, for `_loaded` to parse (the text `null` where the
    record has none, which it doesn't parse)."""
    if pg:
        return Record.data[field_id]
    return type_coerce(
        func.json_quote(func.json_extract(Record.data, f'$."{field_id}"')), String
    )


def _loaded(value: Any, pg: bool) -> Any:
    """A value `_field_value` read, as the value (None: the record has none)."""
    if pg or value is None:
        return value
    return None if value == "null" else json.loads(value)


def _descends(ancestor_id: uuid.UUID, hops: int):
    """The record sits `hops` levels below `ancestor_id` (1: its child)."""
    if hops == 1:
        return Record.parent_record_id == ancestor_id
    return _exists_up(hops - 1, lambda a: a.parent_record_id == ancestor_id)


def _base_query(session: Session, query: ResolvedQuery, is_postgres: bool = False):
    q = session.query(Record).filter(Record.deleted_at.is_(None))
    if query.dataset_id is not None:
        q = q.filter(Record.dataset_id == query.dataset_id)
    if query.schema_id is not None:
        q = q.filter(Record.schema_id == query.schema_id)
    if query.parent_record_id is not None:
        q = q.filter(Record.parent_record_id == query.parent_record_id)
    if query.within is not None:
        ancestor_id, hops = query.within
        q = q.filter(_descends(ancestor_id, hops))
    if query.beneath is not None:
        ancestor_id, deepest = query.beneath
        # Every kind beneath the record: one level down, two, ... to the
        # deepest kind there is (a record's kind fixes how far down it sits).
        q = q.filter(
            or_(*[_descends(ancestor_id, h) for h in range(1, deepest + 1)])
            if deepest
            else false()
        )
    for key, value in query.field_filters:
        if is_postgres:
            # @> containment uses the GIN index on PostgreSQL.
            # _coerce_json_value converts "30" → 30 so numeric/bool fields match correctly.
            doc = json.dumps({key: _coerce_json_value(value)})
            q = q.filter(Record.data.op("@>")(cast(literal(doc), PG_JSONB)))
        else:
            # SQLite: the value as text (a cast of json_extract's unquoted
            # scalar), so a number 30 matches the filter's "30".
            q = q.filter(field_value(Record, key, "text") == value)
    if query.filter_tree is not None:
        q = q.filter(_build_filter_condition(query.filter_tree, is_postgres))
    if query.search:
        q = q.filter(text_match(query.search, is_postgres))
    if query.created_after is not None:
        q = q.filter(Record.created_at >= query.created_after)
    if query.created_before is not None:
        q = q.filter(Record.created_at < query.created_before)
    return q


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def text_match(search: TextSearch, is_postgres: bool = False, entity: Any = Record):
    """The one rule for which records a text search finds (see TextSearch):
    a value of one of its fields contains the term, case-insensitively, or
    the record's id starts with it. A value is a top-level string or number,
    a list's string or number items, or the `filename` of a file (or of each
    file in a list); keys, hashes, sizes and nested structure never match.

    One correlated EXISTS over the record's own JSON (`json_each` on SQLite,
    `jsonb_each`/`jsonb_array_elements` on PostgreSQL), so a search stays one
    statement. It reads every candidate row's data: no index serves a
    substring match (a trigram index over the values would, on PostgreSQL).
    `entity`: the records asked about, when not the statement's own (a
    record above it)."""
    like = _like_pattern(search.term)
    matches = []
    if search.field_ids:
        matches.append(
            _values_contain(list(search.field_ids), like, is_postgres, entity)
        )
    digits = search.term.strip().lower().replace("-", "")
    span = prefix_span(digits) if len(digits) >= ID_PREFIX_MIN else None
    if span is not None:
        matches.append(entity.id.between(*span))
    return or_(*matches) if matches else false()


def _values_contain(
    field_ids: list[str], like: str, is_postgres: bool, entity: Any = Record
):
    """EXISTS a top-level entry of one of `field_ids` whose value, a list
    item of it, or a file's name in either, contains `like`."""
    entry: Any
    entry_type: Any
    item: Any
    item_type: Any
    if is_postgres:
        # render_derived names the columns (`AS e(key, value)`), so they
        # don't depend on how PostgreSQL names a set-returning function's.
        entry = (
            func.jsonb_each(entity.data).table_valued("key", "value").render_derived()
        )
        entry_type = func.jsonb_typeof(entry.c.value)
        items = case(
            (entry_type == "array", entry.c.value),
            else_=cast(literal_column("'[]'"), PG_JSONB),
        )
        item = func.jsonb_array_elements(items).table_valued("value").render_derived()
        item_type = func.jsonb_typeof(item.c.value)
        scalars, objects = ["string", "number"], "object"

        def text_of(value: Any) -> Any:
            return value.op("#>>")(literal_column("'{}'"))

        def name_of(value: Any) -> Any:
            return value.op("->>")(literal_column("'filename'"))
    else:
        entry = func.json_each(entity.data).table_valued("key", "value", "type")
        entry_type = entry.c.type
        items = case((entry_type == "array", entry.c.value), else_=literal("[]"))
        item = func.json_each(items).table_valued("value", "type")
        item_type = item.c.type
        scalars, objects = ["text", "integer", "real"], "object"

        def text_of(value: Any) -> Any:
            return value

        def name_of(value: Any) -> Any:
            return func.json_extract(value, "$.filename")

    def found(value: Any, kind: Any) -> Any:
        return or_(
            and_(kind.in_(scalars), text_of(value).ilike(like, escape="\\")),
            and_(kind == objects, name_of(value).ilike(like, escape="\\")),
        )

    in_a_list = (
        select(literal(1))
        .select_from(item)
        .where(found(item.c.value, item_type))
        .exists()
    )
    return (
        select(literal(1))
        .select_from(entry)
        .where(
            entry.c.key.in_(field_ids),
            or_(found(entry.c.value, entry_type), in_a_list),
        )
        .exists()
    )


def _build_filter_condition(node: FilterNode, pg: bool = False):
    if isinstance(node, FilterGroup):
        clauses = [_build_filter_condition(c, pg) for c in node.conditions]
        return and_(*clauses) if node.op == "and" else or_(*clauses)
    rel = node.rel
    if rel.direction == "up":
        return _exists_up(rel.hops, lambda a: _build_leaf_condition(node, a, pg))
    if rel.direction == "down":
        return _exists_down(
            rel.hops, rel.schema_id, lambda d: _build_leaf_condition(node, d, pg)
        )
    return _build_leaf_condition(node, Record, pg)


def _open_notes_condition(node: FilterCondition, entity: Any):
    """Whether a record has (`value` true) or hasn't threads of notes not yet
    resolved (`civex.domain.notes`)."""
    open_note = (
        select(literal(1))
        .where(
            RecordNote.record_id == entity.id,
            RecordNote.thread_id.is_(None),
            RecordNote.resolved_at.is_(None),
            RecordNote.deleted_at.is_(None),
        )
        .exists()
    )
    return open_note if node.value else not_(open_note)


def _build_leaf_condition(node: FilterCondition, entity: Any, pg: bool = False):
    if node.field == note_rules.OPEN_NOTES_FILTER:
        return _open_notes_condition(node, entity)
    text_value = field_value(entity, node.field, "text")
    if node.op == "is_null":
        # The value as text is SQL NULL both when the key is absent and when it
        # holds JSON null, on both backends.
        return text_value.is_(None) if node.value else text_value.isnot(None)
    if node.op == "contains":
        return text_value.ilike(f"%{node.value}%")
    if pg and node.op in ("eq", "in"):
        values = node.value if node.op == "in" else [node.value]
        if values and all(_contains_same(node.dtype, v) for v in values):
            return or_(*[_contains(entity, node.field, v) for v in values])
    if node.op == "in":
        return or_(
            *[_typed_comparison(entity, node.field, "eq", v) for v in node.value]
        )
    return _typed_comparison(entity, node.field, node.op, node.value)


# The JSON type every stored value of a field type has (values are checked on
# every write, and a field's type never changes), by `_typed_comparison`'s
# reading of a filter value.
_JSON_TYPE_OF_DTYPE = {
    "integer": "number",
    "float": "number",
    "boolean": "boolean",
    "string": "text",
    "enum": "text",
    "url": "text",
    "date": "text",
    "datetime": "text",
    "reference": "text",
}


def _value_kind(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return None


def _contains_same(dtype: str | None, value: Any) -> bool:
    """Whether `data @> {field: value}` (JSONB containment, which the GIN index
    `ix_records_data_gin` answers) matches exactly the records `_typed_comparison`
    does for `eq`: when the field's stored values are of the JSON type the
    comparison reads `value` as. Numbers then compare numerically in both
    (JSONB's numeric equality has 1 == 1.0), strings exactly, booleans as
    booleans. A string compared with a number field (which `_typed_comparison`
    reads as text, matching 30 to "30") is left to it."""
    kind = _value_kind(value)
    if isinstance(value, float) and not math.isfinite(value):
        return False  # not JSON
    return kind is not None and _JSON_TYPE_OF_DTYPE.get(dtype or "") == kind


def _contains(entity: Any, field_id: str, value: Any):
    doc = json.dumps({field_id: value})
    return entity.data.op("@>")(cast(literal(doc), PG_JSONB))


def _typed_comparison(entity: Any, field_id: str, op: str, value: Any):
    """Compare a JSON field against `value`, reading the field as the kind of
    value it is compared with (as parsed from the filter's JSON body), so e.g.
    30 compares numerically rather than lexically. Through `field_value`, so
    a managed field index of that kind serves it."""
    typed_value: Any
    kind = _value_kind(value) or "text"
    typed_col = field_value(entity, field_id, kind)
    if kind == "number":
        typed_value = float(value)
    else:
        typed_value = value
    if op == "eq":
        return typed_col == typed_value
    if op == "ne":
        return typed_col != typed_value
    if op == "gt":
        return typed_col > typed_value
    if op == "gte":
        return typed_col >= typed_value
    if op == "lt":
        return typed_col < typed_value
    if op == "lte":
        return typed_col <= typed_value
    raise ValidationError(f"Unsupported filter operator '{op}'")


def _to_dto(row: Record) -> RecordDTO:
    return RecordDTO(
        id=row.id,
        dataset_id=row.dataset_id,
        schema_id=row.schema_id,
        schema_name=row.schema.name if row.schema else "unknown",
        parent_record_id=row.parent_record_id,
        data=row.data or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def parent_allows_restore(record_model, stamp):
    """A condition on records being brought back by a schema's or collection's
    restore: none above it, or the one above is live, or it was deleted at the
    same moment (and so comes back in the same restore). The one rule both
    restores (and sync, which uses them) follow: a record comes back only
    where it could be added."""
    from sqlalchemy import exists, or_
    from sqlalchemy.orm import aliased

    above = aliased(record_model)
    return or_(
        record_model.parent_record_id.is_(None),
        exists().where(
            above.id == record_model.parent_record_id,
            or_(above.deleted_at.is_(None), above.deleted_at == stamp),
        ),
    )
