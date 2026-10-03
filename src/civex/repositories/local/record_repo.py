from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, cast, delete, func, literal, or_, select, String, update
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Session, aliased

from civex.db.models import Dataset, Record, RecordReference, Schema, WorkflowJob
from civex.domain.dtos import RecordDTO
from civex.domain.exceptions import NotFoundError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode, SortKey
from civex.domain.query import ResolvedQuery
from civex.repositories.local._bucketing import day_bucket
from civex.repositories.local._jobs import bulk_delete_jobs
from civex.repositories.local._table_query import compare, fold_group
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
            span = _prefix_span(prefix)
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
            counts.setdefault(parent_id, {})[schema_name] = n
        return counts

    def _by_schema_query(self, schema_id: uuid.UUID, search: str | None):
        q = self._s.query(Record).filter(
            Record.schema_id == schema_id, Record.deleted_at.is_(None)
        )
        if search:
            q = q.filter(
                or_(
                    cast(Record.data, String).ilike(f"%{search}%"),
                    cast(Record.id, String).ilike(f"{search}%"),
                )
            )
        return q

    def list_by_schema(
        self,
        schema_id: uuid.UUID,
        search: str | None = None,
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
        search: str,
        limit: int = 20,
        dataset_id: uuid.UUID | None = None,
    ) -> list[RecordDTO]:
        """Live records of any schema matching `search`, best match first.

        One query across every schema (and, unless `dataset_id` narrows it,
        every collection). Records whose collection or schema is soft-deleted
        are left out, even though the record row itself may not be marked.
        On PostgreSQL the match is the same indexed full-text search the
        explorer uses, ranked by relevance; elsewhere it is a substring match
        on the record's data, newest first. An id prefix always matches, so a
        pasted id finds its record."""
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
        like = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        id_match = cast(Record.id, String).ilike(f"{like}%", escape="\\")
        newest: list[Any] = [Record.created_at.desc(), Record.id.desc()]
        if self._pg:
            tsquery = func.plainto_tsquery("simple", search)
            q = q.filter(or_(Record.search_vector.op("@@")(tsquery), id_match))
            q = q.order_by(func.ts_rank(Record.search_vector, tsquery).desc(), *newest)
        else:
            q = q.filter(
                or_(
                    cast(Record.data, String).ilike(f"%{like}%", escape="\\"),
                    id_match,
                )
            ).order_by(*newest)
        return [_to_dto(r) for r in q.limit(limit).all()]

    def count_schema_matches(
        self, schema_id: uuid.UUID, search: str | None = None
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
    ) -> RecordDTO:
        # search_vector is maintained by a Postgres trigger (CIVEX-173) so it
        # can't go stale on writes that don't go through this repo; unused on
        # SQLite (see models._TSVECTOR).
        row = Record(
            dataset_id=dataset_id,
            schema_id=schema_id,
            data=data,
            parent_record_id=parent_record_id,
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

    def delete_many(self, ids: list[uuid.UUID]) -> None:
        """Soft-delete every live record in `ids`."""
        now = datetime.now(timezone.utc)
        for chunk in _chunks(ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk), Record.deleted_at.is_(None))
                .values(deleted_at=now)
                .execution_options(synchronize_session=False)
            )
        self._s.expire_all()

    def restore_many(self, ids: list[uuid.UUID]) -> None:
        for chunk in _chunks(ids):
            self._s.execute(
                update(Record)
                .where(Record.id.in_(chunk))
                .values(deleted_at=None)
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
        if is_postgres:
            q = q.filter(
                Record.search_vector.op("@@")(
                    func.plainto_tsquery("simple", query.search)
                )
            )
        else:
            q = q.filter(cast(Record.data, String).ilike(f"%{query.search}%"))
    return q


def _build_filter_condition(node: FilterNode):
    if isinstance(node, FilterGroup):
        return fold_group(node, _build_filter_condition)
    rel = node.rel
    if rel.direction == "up":
        return _exists_up(rel.hops, lambda a: _build_leaf_condition(node, a))
    if rel.direction == "down":
        return _exists_down(
            rel.hops, rel.schema_id, lambda d: _build_leaf_condition(node, d)
        )
    return _build_leaf_condition(node, Record)


def _build_leaf_condition(node: FilterCondition, entity: Any):
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
    return compare(typed_col, op, typed_value)


def _prefix_span(prefix: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The lowest and highest ids that start with `prefix` (hex, dashes
    optional), or None when nothing can: not hex, or longer than an id."""
    digits = prefix.lower().replace("-", "")
    if (
        not digits
        or len(digits) > 32
        or any(c not in "0123456789abcdef" for c in digits)
    ):
        return None
    pad = 32 - len(digits)
    return uuid.UUID(digits + "0" * pad), uuid.UUID(digits + "f" * pad)


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
