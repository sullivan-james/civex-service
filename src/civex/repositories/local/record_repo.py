from __future__ import annotations

import json
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
    update,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Session, aliased

from civex.db.models import (
    Dataset,
    Record,
    RecordNote,
    RecordReference,
    Schema,
    WorkflowJob,
)
from civex.domain import review as review_rules
from civex.domain.dtos import RecordDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode, SortKey
from civex.domain.query import ID_PREFIX_MIN, ResolvedQuery, TextSearch
from civex.domain.summary import RawSummary, SummaryPlan
from civex.repositories.local._ids import prefix_span
from civex.repositories.local._bucketing import day_bucket
from civex.repositories.local._jobs import bulk_delete_jobs
from civex.repositories.protocols import RecordGrowthRow


def _order_by(sort: list[SortKey] | None) -> list[Any]:
    """ORDER BY terms for a view-style sort on JSON fields: nulls (absent or
    JSON null) always last regardless of direction, numeric types compared
    as numbers, everything else (ISO dates/datetimes included) as text. A key
    on an ancestor's field sorts by that ancestor record's value."""
    terms: list[Any] = []
    for key in sort or []:
        if key.rel.direction == "up":
            value = _up_value(key.rel.hops, key.field_id, key.numeric)
        else:
            col = Record.data[key.field_id]
            value = col.as_float() if key.numeric else col.as_string()
        terms.append(value.is_(None))
        terms.append(value.desc() if key.descending else value.asc())
    return terms


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


def _up_value(hops: int, field_id: str, numeric: bool):
    """The value of `field_id` on the ancestor `hops` levels above the outer
    Record, as a correlated scalar -- NULL when there is none."""
    aliases = [aliased(Record) for _ in range(hops)]
    col = aliases[-1].data[field_id]
    value = col.as_float() if numeric else col.as_string()
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
        # created_at alone isn't a total order (bulk inserts share
        # timestamps), so ties are broken on id -- otherwise OFFSET pages can
        # repeat or skip rows.
        q = q.order_by(*_order_by(query.sort), Record.created_at, Record.id)
        if offset:
            q = q.offset(offset)
        return [_to_dto(r) for r in q.limit(limit).all()]

    def count(self, query: ResolvedQuery) -> int:
        return _base_query(self._s, query, self._pg).count()

    def count_open_notes(self, query: ResolvedQuery) -> tuple[int, int]:
        """(notes not yet resolved, records holding them) among the records
        `query` lists. One statement."""
        listed = _base_query(self._s, query, self._pg).with_entities(Record.id)
        notes, records = (
            self._s.query(
                func.count(RecordNote.id),
                func.count(func.distinct(RecordNote.record_id)),
            )
            .filter(
                RecordNote.record_id.in_(listed.scalar_subquery()),
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
        target, referrer = aliased(Record), aliased(Record)
        where = (
            target.dataset_id == dataset_id,
            target.deleted_at.is_(None),
            referrer.dataset_id != dataset_id,
            referrer.deleted_at.is_(None),
            rr.field_id.in_(field_ids),
        )

        def joined(*cols):
            return (
                select(*cols)
                .select_from(rr)
                .join(referrer, referrer.id == rr.record_id)
                .join(target, target.id == rr.target_id)
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

    def set_review(self, ids: list[uuid.UUID], review: dict[str, Any] | None) -> None:
        """Give every record in `ids` this review (None clears it), one
        statement per chunk. Not an edit: each keeps its `updated_at`."""
        for chunk in _chunks(ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(review=review, updated_at=Record.updated_at)
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def open_note_counts(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many notes each of these records has that are not yet resolved
        (records with none are left out). One grouped query per chunk."""
        out: dict[uuid.UUID, int] = {}
        for chunk in _chunks(ids):
            for rid, n in (
                self._s.query(RecordNote.record_id, func.count(RecordNote.id))
                .filter(
                    RecordNote.record_id.in_(chunk),
                    RecordNote.resolved_at.is_(None),
                    RecordNote.deleted_at.is_(None),
                )
                .group_by(RecordNote.record_id)
            ):
                out[rid] = n
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
            q = q.filter(_typed_comparison(Record.data[field_id], "eq", value))
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

    def restore_many(self, ids: list[uuid.UUID]) -> None:
        for chunk in _chunks(ids):
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
        if hops == 1:
            q = q.filter(Record.parent_record_id == ancestor_id)
        else:
            q = q.filter(
                _exists_up(hops - 1, lambda a: a.parent_record_id == ancestor_id)
            )
    for key, value in query.field_filters:
        if is_postgres:
            # @> containment uses the GIN index on PostgreSQL.
            # _coerce_json_value converts "30" → 30 so numeric/bool fields match correctly.
            doc = json.dumps({key: _coerce_json_value(value)})
            q = q.filter(Record.data.op("@>")(cast(literal(doc), PG_JSONB)))
        else:
            # SQLite: json_extract (via .as_string()) returns the *unquoted* scalar
            # but preserves its storage class, so a numeric field would compare as
            # INTEGER 30 != TEXT '30'. Casting the extracted value to TEXT normalises
            # both strings and numbers to match the string filter value.
            # (Plain cast(data[key], String) would instead yield the JSON form '"S02"'.)
            q = q.filter(cast(Record.data[key].as_string(), String) == value)
    if query.filter_tree is not None:
        q = q.filter(_build_filter_condition(query.filter_tree))
    if query.search:
        q = q.filter(text_match(query.search, is_postgres))
    return q


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def text_match(search: TextSearch, is_postgres: bool = False):
    """The one rule for which records a text search finds (see TextSearch):
    a value of one of its fields contains the term, case-insensitively, or
    the record's id starts with it. A value is a top-level string or number,
    a list's string or number items, or the `filename` of a file (or of each
    file in a list); keys, hashes, sizes and nested structure never match.

    One correlated EXISTS over the record's own JSON (`json_each` on SQLite,
    `jsonb_each`/`jsonb_array_elements` on PostgreSQL), so a search stays one
    statement. It reads every candidate row's data: no index serves a
    substring match (a trigram index over the values would, on PostgreSQL)."""
    like = _like_pattern(search.term)
    matches = []
    if search.field_ids:
        matches.append(_values_contain(list(search.field_ids), like, is_postgres))
    digits = search.term.strip().lower().replace("-", "")
    span = prefix_span(digits) if len(digits) >= ID_PREFIX_MIN else None
    if span is not None:
        matches.append(Record.id.between(*span))
    return or_(*matches) if matches else false()


def _values_contain(field_ids: list[str], like: str, is_postgres: bool):
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
            func.jsonb_each(Record.data).table_valued("key", "value").render_derived()
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
        entry = func.json_each(Record.data).table_valued("key", "value", "type")
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


def _build_filter_condition(node: FilterNode):
    if isinstance(node, FilterGroup):
        clauses = [_build_filter_condition(c) for c in node.conditions]
        return and_(*clauses) if node.op == "and" else or_(*clauses)
    rel = node.rel
    if rel.direction == "up":
        return _exists_up(rel.hops, lambda a: _build_leaf_condition(node, a))
    if rel.direction == "down":
        return _exists_down(
            rel.hops, rel.schema_id, lambda d: _build_leaf_condition(node, d)
        )
    return _build_leaf_condition(node, Record)


def _review_condition(node: FilterCondition, entity: Any):
    """A condition on what `civex.domain.review` adds to a record: its review
    status (`none` is no review) or whether it has notes not yet resolved."""
    if node.field == review_rules.OPEN_NOTES_FILTER:
        open_note = (
            select(literal(1))
            .where(
                RecordNote.record_id == entity.id,
                RecordNote.resolved_at.is_(None),
                RecordNote.deleted_at.is_(None),
            )
            .exists()
        )
        return open_note if node.value else not_(open_note)
    status = entity.review["status"].as_string()

    def is_(value: Any):
        return status.is_(None) if value == review_rules.NONE else status == value

    if node.op == "in":
        return or_(*[is_(v) for v in node.value]) if node.value else false()
    if node.op == "ne":
        if node.value == review_rules.NONE:
            return status.isnot(None)
        return or_(status.is_(None), status != node.value)
    return is_(node.value)


def _build_leaf_condition(node: FilterCondition, entity: Any):
    if node.field in review_rules.FILTERS:
        return _review_condition(node, entity)
    col = entity.data[node.field]
    if node.op == "is_null":
        # `.as_string()` (->>` on PG, plain json_extract on SQLite) collapses
        # "key absent" and "key present with JSON null" to the same SQL NULL
        # on both backends -- the bare accessor doesn't: SQLite's JSON_QUOTE
        # wrapper turns a missing key into the *string* "null" rather than
        # SQL NULL, and PG's `->` returns a non-NULL jsonb 'null' for an
        # explicit null value.
        return col.as_string().is_(None) if node.value else col.as_string().isnot(None)
    if node.op == "contains":
        return col.as_string().ilike(f"%{node.value}%")
    if node.op == "in":
        return or_(*[_typed_comparison(col, "eq", v) for v in node.value])
    return _typed_comparison(col, node.op, node.value)


def _typed_comparison(col, op: str, value: Any):
    """Compare a JSON field against `value`, dispatching to the JSON
    accessor variant matching value's own type (as parsed from the filter's
    JSON body) so e.g. 30 compares numerically rather than lexically."""
    typed_value: Any
    if isinstance(value, bool):
        typed_col, typed_value = col.as_boolean(), value
    elif isinstance(value, (int, float)):
        typed_col, typed_value = col.as_float(), float(value)
    else:
        typed_col, typed_value = col.as_string(), value
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
        review=row.review,
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
