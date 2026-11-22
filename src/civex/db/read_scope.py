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

from sqlalchemy import ColumnElement, event, false, select, true
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


def criteria(scope: ReadScope) -> list[Any]:
    """The loader criteria that keep a session within `scope`."""
    seen = select(Record.id).where(_in_scope(Record.dataset_id, scope))
    seen_datasets = select(Dataset.id).where(_in_scope(Dataset.id, scope))
    seen_notes = select(RecordNote.id).where(RecordNote.record_id.in_(seen))
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
        # restricted reader cannot place in a collection, so it is not shown.
        with_loader_criteria(
            AuditLog,
            AuditLog.entity_type.notin_(["record", "dataset", _NOTE])
            | ((AuditLog.entity_type == "record") & AuditLog.entity_id.in_(seen))
            | (
                (AuditLog.entity_type == "dataset")
                & AuditLog.entity_id.in_(seen_datasets)
            )
            | ((AuditLog.entity_type == _NOTE) & AuditLog.entity_id.in_(seen_notes)),
            include_aliases=True,
        ),
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


def restricted(session: Session) -> bool:
    """Whether `session` is limited to some collections: what answers from
    statistics of the whole table (an estimated count) must not be used, since
    it counts what the caller may not see."""
    return bool(session.info.get(_RESTRICTED))
