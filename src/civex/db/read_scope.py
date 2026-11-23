"""A collection the caller may not read is not there.

`install(session, scope)` limits every ORM query the session makes, the
statements the services never see, to the collections the caller may read
(`domain.permissions.ReadScope`): a record, a note, a reference, a history
entry or a file's use that belongs to a hidden collection is simply absent, so
no list, count, search, summary, export or lookup can show it and a direct
request for it finds nothing (a 404, never a 403). It is one rule applied at
the one layer every query goes through, not a check each service must remember.

`unscoped(session)` lifts it for the sync authority, which sees the whole
project to settle a push and then asks `Permissions` about each thing itself.
Nothing else should use it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import ColumnElement, and_, event, false, or_, select, true
from sqlalchemy.orm import Session, with_loader_criteria

from civex.db.models import (
    AuditLog,
    Dataset,
    FileReference,
    JobAffectedRecord,
    Record,
    RecordNote,
    RecordReference,
)
from civex.domain.permissions import ReadScope

_OFF = "civex_read_scope_off"
_RESTRICTED = "civex_read_scope_on"
# Entities, not tables: what an audit entry is about.
_NOTE = "note"


def _in_scope(column: Any, scope: ReadScope) -> ColumnElement[bool]:
    if scope.only is not None:
        return column.in_(list(scope.only)) if scope.only else false()
    return column.notin_(list(scope.hidden)) if scope.hidden else true()


# Audit entries about these are visible to everyone: a kind of record, its
# fields, and the filters and dashboards a project shares are not hidden with a
# collection. Every other entity type is judged by `_entry_visible` or, if it
# is not named here, hidden: a new kind of entry carrying collection data must
# be placed deliberately, never shown by default.
_SHARED_ENTITIES = ("schema", "field", "view", "dashboard")


def _entry_visible(scope: ReadScope) -> ColumnElement[bool]:
    """Whether an audit entry is about something the caller may see: one
    probe by key per entry (never `IN (subquery)`, which under OR is planned as
    a scan of the whole table). A collection's own entries need no probe: the
    entry's id is the collection's."""
    # The tables, not the ORM entities: the loader criteria below would add
    # their own (and costlier) filters to a subquery that already carries the
    # rule. Scalar subqueries, not EXISTS or a join, so the planner can only
    # probe by key for each entry (it hashes a whole collection otherwise); an
    # entry whose thing is gone gets NULL, which is not in any scope.
    records = Record.__table__
    notes = RecordNote.__table__
    record_in = (
        select(records.c.dataset_id)
        .where(records.c.id == AuditLog.entity_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    note_in = (
        select(records.c.dataset_id)
        .select_from(notes.join(records, records.c.id == notes.c.record_id))
        .where(notes.c.id == AuditLog.entity_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    dataset = _in_scope(AuditLog.entity_id, scope)
    record = _in_scope(record_in, scope)
    note = _in_scope(note_in, scope)
    return or_(
        AuditLog.entity_type.in_(_SHARED_ENTITIES),
        and_(AuditLog.entity_type == "record", record),
        and_(AuditLog.entity_type == "dataset", dataset),
        and_(AuditLog.entity_type == _NOTE, note),
    )


def criteria(scope: ReadScope) -> list[Any]:
    """The loader criteria that keep a session within `scope`."""
    seen = select(Record.id).where(_in_scope(Record.dataset_id, scope))
    return [
        with_loader_criteria(
            Record, _in_scope(Record.dataset_id, scope), include_aliases=True
        ),
        with_loader_criteria(
            Dataset, _in_scope(Dataset.id, scope), include_aliases=True
        ),
        with_loader_criteria(
            RecordNote, RecordNote.record_id.in_(seen), include_aliases=True
        ),
        with_loader_criteria(
            RecordReference, RecordReference.record_id.in_(seen), include_aliases=True
        ),
        # Only uses by records the caller can see: a file a job or a release
        # holds is not theirs by that (a release bundles records from anywhere).
        with_loader_criteria(
            FileReference, FileReference.record_id.in_(seen), include_aliases=True
        ),
        with_loader_criteria(
            JobAffectedRecord,
            JobAffectedRecord.record_id.in_(seen),
            include_aliases=True,
        ),
        # A history entry is about a thing; it is visible when the thing is. A
        # record whose row is gone (purged) leaves only a tombstone, which a
        # restricted reader cannot place in a collection, so it is not shown;
        # nor is an entry of a release, whose bundle and counts cover the whole
        # project, or of any type not listed above.
        with_loader_criteria(AuditLog, _entry_visible(scope), include_aliases=True),
    ]


def install(session: Session, scope_of: Callable[[], ReadScope]) -> None:
    """Keep `session` within the collections `scope_of()` allows. Nothing is
    added for a caller who may read everything."""
    if scope_of().unrestricted:
        return
    session.info[_RESTRICTED] = True

    @event.listens_for(session, "do_orm_execute")
    def _limit(state: Any) -> None:
        if session.info.get(_OFF):
            return
        if state.is_column_load or state.is_relationship_load:
            return
        if state.is_select or state.is_update or state.is_delete:
            state.statement = state.statement.options(*criteria(scope_of()))


@contextmanager
def unscoped(session: Session) -> Iterator[None]:
    """The whole project is visible inside the block (see the module doc)."""
    before = session.info.get(_OFF, False)
    session.info[_OFF] = True
    try:
        yield
    finally:
        session.info[_OFF] = before


@contextmanager
def scoped(session: Session) -> Iterator[None]:
    """The caller's own limit applies inside the block, even within `unscoped`:
    for a question about what the caller may see asked from work that otherwise
    sees everything."""
    before = session.info.get(_OFF, False)
    session.info[_OFF] = False
    try:
        yield
    finally:
        session.info[_OFF] = before


def restricted(session: Session) -> bool:
    """Whether `session` is limited to some collections: what answers from
    statistics of the whole table (an estimated count) must not be used, since
    it counts what the caller may not see."""
    return bool(session.info.get(_RESTRICTED))
