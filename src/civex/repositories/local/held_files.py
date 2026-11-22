"""The files a set of records holds, read by the database alone.

A list of a collection's files must not load its records to find them: what
it counts (how many, how big, on which drive, of which kind) is in the catalog
(`file_references`, `stored_objects`, what the server said it has) and in each
record's file values. A fixed few statements read them for a whole
`ResolvedSet`, whatever its size; no record is put in its response form and
no drive is asked anything.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import String, and_, case, false, func, literal, or_, select
from sqlalchemy import type_coerce, union
from sqlalchemy.orm import Session, aliased

from civex.db.models import (
    FileReference,
    Record,
    ServerFile,
    ServerLack,
    StoredObject,
)
from civex.domain.file_access import HeldFile
from civex.domain.query import ResolvedSet, TextSearch
from civex.repositories.local.record_repo import (
    _base_query,
    _exists_up,
    text_match,
)


def _live(record: Any) -> Any:
    """`record.deleted_at IS NULL`, written so that it is checked on rows
    found another way. SQLite (which keeps no statistics here) otherwise
    takes the index on `deleted_at` to be selective and starts from every
    live record in the project."""
    return case((record.deleted_at.is_(None), 1), else_=0) == 1


def _ids_of(session: Session, picked: ResolvedSet, pg: bool) -> Any:
    """The records the set starts from (before anything beneath them), as a
    statement of their ids."""
    parts: list[Any] = [
        _base_query(session, q, pg).with_entities(Record.id.label("id")).statement
        for q in picked.queries
    ]
    if picked.ids:
        parts.append(
            select(Record.id.label("id")).where(
                Record.id.in_(picked.ids), _live(Record)
            )
        )
    if not parts:
        return select(Record.id.label("id")).where(false())
    return parts[0] if len(parts) == 1 else union(*parts)


def _listed(session: Session, query: Any, pg: bool) -> Any:
    found = (
        _base_query(session, query, pg)
        .with_entities(Record.id.label("id"))
        .statement.subquery()
    )
    return select(found.c.id)


def records_of(session: Session, picked: ResolvedSet, pg: bool) -> Any:
    """A query of the live records in the set. One plain query is itself (its
    own indexes serve it); anything else is `id IN (...)`: the records it
    starts from and, with `below`, everything beneath them, found by walking
    down from them (a recursive query, so it stops at a deleted record as a
    walk a level at a time does)."""
    simple = len(picked.queries) == 1 and not picked.ids and not picked.below
    if simple:
        q = _base_query(session, picked.queries[0], pg)
    else:
        roots = _ids_of(session, picked, pg)
        if not picked.below:
            found = roots.subquery("picked")
            inside: Any = Record.id.in_(select(found.c.id))
        else:
            start = roots.cte("picked")
            tree = select(start.c.id).cte("picked_tree", recursive=True)
            child = aliased(Record)
            tree = tree.union(
                select(child.id).where(
                    child.parent_record_id == tree.c.id, _live(child)
                )
            )
            inside = Record.id.in_(select(tree.c.id))
            if picked.listed is not None:
                inside = and_(
                    inside,
                    or_(
                        Record.id.in_(select(start.c.id)),
                        *[
                            Record.id.in_(_listed(session, q, pg))
                            for q in picked.listed
                        ],
                    ),
                )
        # Live already: what it starts from is, and so is all found beneath.
        q = session.query(Record).filter(inside)
    if picked.schema_ids is not None:
        q = q.filter(Record.schema_id.in_(picked.schema_ids))
    return q


def held_files(
    session: Session,
    picked: ResolvedSet,
    file_fields: dict[str, str],
    search: TextSearch | None,
    depth: int,
    pg: bool,
    following: bool = True,
) -> list[HeldFile]:
    """Every file value the set's records hold in `file_fields` (field id ->
    name), with the copy each record points at and what the server said of
    the file. `search` marks (`found`) the ones whose stored name contains the
    term, or whose record, or a record up to `depth` levels above it, matches
    it as a record search would. `following`: whether this project follows a
    server (else what a server said is not looked up).

    One statement reads the records the catalog says hold a file: just their
    file fields' values and their pointers, never the rest of their data.
    What is rare is asked apart, once each and only when there is any: where
    a file is that its record doesn't point at yet, and (while following a
    server) which files the server said it has or lacks. Ids and times come
    back as the database keeps them (`HeldFile`): turning tens of thousands
    into objects costs more than reading them."""
    if not file_fields:
        return []
    pointer = aliased(FileReference)
    spot = pointer.sha256 + literal("@") + func.coalesce(pointer.volume, literal(""))
    pointers = (
        select(func.string_agg(spot, ",") if pg else func.group_concat(spot, ","))
        .where(pointer.record_id == Record.id)
        .correlate(Record)
        .scalar_subquery()
    )
    found: Any = literal(True)
    needle = ""
    if search is not None:
        needle = search.term.casefold()
        found = or_(
            text_match(search, pg),
            *[
                _exists_up(hops, lambda above: text_match(search, pg, above))
                for hops in range(1, depth + 1)
            ],
        )
    fields = list(file_fields.items())
    rows = (
        records_of(session, picked, pg)
        # Only records the catalog says hold a file are read.
        .filter(
            Record.id.in_(
                select(FileReference.record_id).where(
                    FileReference.record_id.is_not(None)
                )
            )
        )
        .with_entities(
            type_coerce(Record.id, String),
            type_coerce(Record.dataset_id, String),
            type_coerce(Record.created_at, String),
            pointers,
            found,
            *[_value(field_id, pg) for field_id, _ in fields],
        )
    )
    out: list[HeldFile] = []
    waiting = False
    for rid, dataset_id, made, pointed, hit, *values in rows:
        at: dict[str, str] = {}
        for entry in (pointed or "").split(","):
            digest, _, volume = entry.partition("@")
            at[digest] = volume
        for (_, field_name), value in zip(fields, values):
            if value is None:
                continue
            if isinstance(value, str):
                value = json.loads(value)
            for ref in value if isinstance(value, list) else (value,):
                if not isinstance(ref, dict):
                    continue
                digest = ref.get("sha256")
                if not digest or digest not in at:
                    # Not a file, or one the catalog doesn't know the record
                    # holds: the catalog is what is counted.
                    continue
                name = ref.get("filename")
                name = name if isinstance(name, str) else ""
                volume = at[digest] or None
                waiting = waiting or volume is None
                out.append(
                    HeldFile(
                        rid,
                        dataset_id,
                        made,
                        field_name,
                        digest,
                        name,
                        _whole(ref.get("size")),
                        volume,
                        (),
                        False,
                        False,
                        bool(hit) or bool(needle and needle in name.casefold()),
                    )
                )
    if waiting:
        out = _with_copies(session, out)
    if following:
        out = _with_server(session, out)
    return out


def _value(field_id: str, pg: bool) -> Any:
    """A record's value for one field: as JSON text on SQLite (NULL where the
    record has none, so nothing is parsed for it), parsed on PostgreSQL."""
    if pg:
        return Record.data[field_id]
    return type_coerce(func.json_extract(Record.data, f'$."{field_id}"'), String)


def _with_copies(session: Session, held: list[HeldFile]) -> list[HeldFile]:
    """Where a file is whose record points at no copy yet, when a drive here
    holds one all the same. One statement, for however many."""
    unpointed = select(FileReference.sha256).where(
        FileReference.volume.is_(None), FileReference.record_id.is_not(None)
    )
    on: dict[str, tuple[str, ...]] = {}
    for digest, volume in session.execute(
        select(StoredObject.sha256, StoredObject.volume).where(
            StoredObject.sha256.in_(unpointed)
        )
    ):
        on[digest] = (*on.get(digest, ()), volume)
    if not on:
        return held
    return [
        h._replace(stored_on=on[h.sha256]) if h.volume is None and h.sha256 in on else h
        for h in held
    ]


def _with_server(session: Session, held: list[HeldFile]) -> list[HeldFile]:
    """What the server said of each file: that it holds it, or hasn't got it.
    Two statements (each list whole; a project's files, at most)."""
    has = set(session.execute(select(ServerFile.sha256)).scalars())
    lacks = set(session.execute(select(ServerLack.sha256)).scalars())
    if not has and not lacks:
        return held
    return [
        h._replace(on_server=h.sha256 in has, server_lacks=h.sha256 in lacks)
        for h in held
    ]


def _whole(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def shared_copies(session: Session) -> dict[tuple[str, str | None], int]:
    """The copies, (sha256, volume), that more than one live record points
    at, with how many. One statement over the catalog: the files cited more
    than once are found from its index alone, and only their records are
    looked at."""
    cited_twice = (
        select(FileReference.sha256)
        .where(FileReference.record_id.is_not(None))
        .group_by(FileReference.sha256)
        .having(func.count() > 1)
    )
    use = aliased(FileReference)
    user = aliased(Record)
    rows = session.execute(
        select(use.sha256, use.volume, func.count())
        .join(user, user.id == use.record_id)
        .where(_live(user), use.sha256.in_(cited_twice))
        .group_by(use.sha256, use.volume)
        .having(func.count() > 1)
    )
    return {(digest, volume): int(n) for digest, volume, n in rows}


def holders(session: Session, picked: ResolvedSet, pg: bool) -> list[Any]:
    """The ids (as the database keeps them) of the set's records that the
    catalog says hold a file, in the order records are listed. One
    statement."""
    return [
        rid
        for (rid,) in records_of(session, picked, pg)
        .filter(
            Record.id.in_(
                select(FileReference.record_id).where(
                    FileReference.record_id.is_not(None)
                )
            )
        )
        .order_by(Record.created_at, Record.id)
        .with_entities(type_coerce(Record.id, String))
    ]
