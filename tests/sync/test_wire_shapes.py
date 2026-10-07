"""What travels is declared (`WIRE_FIELDS`), and changing it is a protocol change.

A snapshot is built from a thing's DTO and written back by column name, so
without these a renamed DTO key or a new column would quietly change what
devices exchange, and an older device would drop it without a word."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from civex.db.models import AuditLog
from civex.domain.sync import ENTITY_ORDER, PROTOCOL_MAX, WIRE_FIELDS, SyncEntry
from civex.repositories.local.sync_repo import _MODELS, _NOT_WRITTEN

from .peers import build_study, new_id, principal

# Carried for a collection beside its own columns: its schema list.
NOT_COLUMNS = {"dataset": {"schema_ids", "schemas"}}


def test_what_travels_is_recorded_for_this_protocol_version():
    recorded = json.loads((Path(__file__).parent / "wire_shapes.json").read_text())
    shape = {kind: sorted(fields) for kind, fields in WIRE_FIELDS.items()}
    assert shape == recorded.get(str(PROTOCOL_MAX)), (
        "WIRE_FIELDS changed: that is a protocol change. Raise PROTOCOL_MAX, record "
        "the new shape under it in wire_shapes.json (keep the old ones), and give "
        "devices on the previous version what they can read."
    )


def test_every_column_of_a_synced_table_travels_or_is_declared_local():
    for kind in ENTITY_ORDER:
        columns = {c.name for c in _MODELS[kind].__table__.columns}
        travels = WIRE_FIELDS[kind] - NOT_COLUMNS.get(kind, set())
        assert columns - _NOT_WRITTEN == travels, kind


def test_a_snapshot_carries_exactly_what_travels(project):
    ctx = project("p")
    build_study(ctx)
    ctx.view_svc.create("encounter", "deep", columns=["site"])
    ctx.commit()
    for kind in ENTITY_ORDER:
        (snapshot,) = ctx.sync_repo.snapshots_page(kind, None, 1)
        assert set(snapshot) == WIRE_FIELDS[kind], kind


def test_a_change_leaves_with_only_what_travels(project):
    ctx = project("p")
    record = build_study(ctx)
    ctx.record_svc.delete(str(record.id))
    ctx.commit()
    (row,) = [e for e in ctx.sync_repo.pending_entries(100) if e.action == "delete"]
    # An entry written by an older civex, holding a key since dropped.
    stored = ctx.audit_svc._s.get(AuditLog, row.id)
    stored.old_data = {**stored.old_data, "natural_name": "x"}
    ctx.audit_svc._s.flush()
    (sent,) = [e for e in ctx.sync_repo.pending_entries(100) if e.action == "delete"]
    assert set(sent.old_data) <= WIRE_FIELDS["record"]


def test_a_change_carrying_what_the_server_does_not_keep_is_refused(project):
    authority = project("authority")
    thing = new_id()
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="schema",
        entity_id=uuid.UUID(thing),
        old_data=None,
        new_data={"id": thing, "name": "thing", "colour": "red"},
        timestamp="2026-01-01T00:00:00+00:00",
    )
    result = authority.authority_svc.push(principal(authority, "laptop"), [entry])
    (answer,) = result.results
    assert answer.status == "rejected" and "colour" in (answer.message or "")
