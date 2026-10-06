"""History is complete: replaying the entries about anything gives what it is now.

Sync will send these entries and nothing else, so a change that wrote no entry
(or a stale one) would never reach another device. This does everything a
person can do to schemas, fields, collections, views and records, then, for
every thing, starts from its create and applies each entry in the order written
(an edit stores only what changed) and checks the result is what is in the
database."""

from __future__ import annotations

import json
from typing import Any

from civex.context import AppContext
from civex.db.models import AuditLog
from civex.domain.audit_diff import AFTER, apply_delta, entry_snapshots


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _entries(ctx: AppContext) -> dict[tuple[str, Any], list[AuditLog]]:
    rows = ctx._session.query(AuditLog).order_by(AuditLog.local_seq).all()
    by_thing: dict[tuple[str, Any], list[AuditLog]] = {}
    for row in rows:
        by_thing.setdefault((row.entity_type, row.entity_id), []).append(row)
    return by_thing


def _current(ctx: AppContext, kind: str, entity_id: Any) -> dict[str, Any] | None:
    """What the database holds for one thing now, as its history snapshot is."""
    if kind == "schema":
        found = ctx.schema_svc._repo.get_by_id(entity_id, include_deleted=True)
    elif kind == "field":
        pair = ctx.schema_svc._repo.find_fields({entity_id}).get(entity_id)
        found = pair
    elif kind == "dataset":
        found = ctx.dataset_svc._datasets.get_by_id(entity_id, include_deleted=True)
    elif kind == "view":
        found = ctx.view_svc._views.get_by_id(entity_id)
    elif kind == "record":
        rows = ctx.record_svc._records.list_by_ids([entity_id])
        found = rows[0] if rows else None
    else:
        raise AssertionError(f"unexpected kind {kind}")
    return _json(found.to_dict()) if found is not None else None


def _replayed(rows: list[AuditLog]) -> tuple[dict[str, Any] | None, str | None]:
    """A thing as its entries leave it, from its create on, and what is wrong
    with the history if it can't be replayed."""
    state: dict[str, Any] | None = None
    for row in rows:
        if row.action == "create":
            state = dict(row.new_data or {})
        elif row.action in ("update", "restore"):
            if row.delta is None:
                state = dict(row.new_data or {})
            elif state is None:
                return None, f"an {row.action} with nothing before it"
            else:
                state = apply_delta(state, row.delta, AFTER)
        elif row.action == "delete" and state is not None:
            state = {**state, "deleted_at": row.timestamp.isoformat()}
    return state, None


def _wrong(ctx: AppContext) -> list[str]:
    problems: list[str] = []
    entries = _entries(ctx)
    purged_schemas = {
        str(i)
        for (k, i), rows in entries.items()
        if k == "schema" and rows[-1].action == "purge"
    }
    for (kind, entity_id), rows in entries.items():
        last = rows[-1]
        now = _current(ctx, kind, entity_id)
        if last.action == "purge":
            if now is not None:
                problems.append(f"{kind} {entity_id} was purged but still exists")
            continue
        if last.action == "delete" and kind == "view":
            # Views are removed outright, so a delete is the whole story.
            if now is not None:
                problems.append(f"view {entity_id}: deleted in history, there now")
            continue
        if now is None:
            # Purging a schema takes its fields with it; its entry says so.
            snapshot = last.new_data or last.old_data or {}  # (identity is enough)
            if kind == "field" and snapshot.get("schema_id") in purged_schemas:
                continue
            problems.append(f"{kind} {entity_id} is gone with no purge entry")
            continue
        if last.action == "delete":
            if now.get("deleted_at") is None:
                problems.append(f"{kind} {entity_id}: deleted in history, live now")
            continue
        replayed, broken = _replayed(rows)
        if broken:
            problems.append(f"{kind} {entity_id}: {broken}")
            continue
        expected = _json(replayed)
        # A schema or collection delete stamps (and a restore clears) its
        # records in one statement, with no entry each: that cascade is what the
        # entry about the schema means, so a record's own clock isn't compared.
        if kind == "record":
            expected.pop("updated_at", None)
            now.pop("updated_at", None)
        # A collection's schemas are its `schema_ids`; the names beside them are
        # for reading, and a schema's rename is recorded as a change to the schema.
        if kind == "dataset":
            expected.pop("schemas", None)
            now.pop("schemas", None)
        if expected != now:
            differs = sorted(
                k for k in set(expected) | set(now) if expected.get(k) != now.get(k)
            )
            problems.append(
                f"{kind} {entity_id}: replaying its history (last: {last.action}) "
                f"gives something else on {differs}"
            )
    return problems


def test_history_describes_everything_a_person_can_do(ctx: AppContext) -> None:
    svc = ctx.schema_svc
    svc.create("encounter")
    svc.add_field("encounter", "site", "string")
    svc.add_field("encounter", "depth", "float")
    svc.create("recording", parent="encounter")
    svc.add_field("recording", "rate", "integer")
    ctx.dataset_svc.create("c")
    ctx.dataset_svc.update("c", schemas=["encounter", "recording"], timezone="UTC")
    ctx.commit()

    enc = ctx.record_svc.add("c", "encounter", {"site": "x", "depth": 1.0})
    rec = ctx.record_svc.add(
        "c", "recording", {"rate": 1}, parent_record_id=str(enc.id)
    )
    ctx.record_svc.update(str(rec.id), {"rate": 2})
    ctx.commit()

    # Schemas and fields: every kind of edit.
    svc.update("encounter", description="a visit", label="Encounter")
    svc.update("recording", display_template="{site} {rate}")
    svc.update_field(
        "encounter", "depth", required=True, restrictions={"min": 0}, label="Depth"
    )
    svc.update_field("encounter", "depth", default_value=1.0)
    svc.reorder_fields(
        "encounter", [f.id for f in reversed(svc.get("encounter").fields)]
    )
    # Renaming a field rewrites the name templates that use it, here in another
    # schema: that is a change to that schema too.
    svc.update_field("encounter", "site", new_name="location")
    svc.delete_field("encounter", "depth")
    depth = svc.get("encounter").deleted_fields[0]
    svc.restore_field("encounter", depth.id)
    ctx.commit()

    # Views and collections.
    ctx.view_svc.create("encounter", "v1", columns=["location"])
    ctx.view_svc.update("encounter", "v1", columns=["location", "depth"])
    ctx.view_svc.create("encounter", "v2")
    ctx.view_svc.delete("encounter", "v2")
    ctx.dataset_svc.update("c", description="study", scope="global")
    ctx.commit()

    # Deleting and bringing back.
    ctx.record_svc.delete(str(rec.id))
    ctx.record_svc.restore(str(rec.id))
    ctx.record_svc.delete(str(enc.id))
    ctx.record_svc.restore(str(enc.id))
    ctx.schema_svc.delete("recording")
    ctx.schema_svc.restore("recording")
    ctx.commit()

    # Renames reach into other things: a collection lists its schemas by name.
    ctx.dataset_svc.delete("c")
    ctx.dataset_svc.restore("c")
    svc.update("recording", new_name="take")
    ctx.commit()

    # Permanent deletion leaves a tombstone, and for a schema takes its fields.
    gone = ctx.record_svc.add("c", "encounter", {"site": "y"})
    ctx.record_svc.delete(str(gone.id))
    ctx.record_svc.purge(str(gone.id))
    svc.create("scratch")
    svc.add_field("scratch", "note", "string")
    svc.delete("scratch")
    svc.purge("scratch")
    ctx.commit()

    # Last, so a later edit of the same fields cannot hide it.
    svc.reorder_fields(
        "encounter", [f.id for f in reversed(svc.get("encounter").fields)]
    )
    ctx.commit()

    problems = _wrong(ctx)
    assert not problems, "\n" + "\n".join(problems)


def test_reordering_fields_is_an_edit_of_each_field_that_moved(ctx: AppContext) -> None:
    ctx.schema_svc.create("thing")
    for name in ("a", "b", "c"):
        ctx.schema_svc.add_field("thing", name, "string")
    fields = ctx.schema_svc.get("thing").fields
    ctx.commit()

    ctx.schema_svc.reorder_fields("thing", [fields[2].id, fields[1].id, fields[0].id])
    ctx.commit()

    entries = _entries(ctx)
    for field in ctx.schema_svc.get("thing").fields:
        last = entries[("field", field.id)][-1]
        assert last.action == "update"
        _, new = entry_snapshots(last.old_data, last.new_data, last.delta)
        assert new["position"] == field.position


def test_renaming_a_field_is_recorded_for_the_templates_it_rewrites(
    ctx: AppContext,
) -> None:
    ctx.schema_svc.create("parent")
    ctx.schema_svc.add_field("parent", "site", "string")
    ctx.schema_svc.create("child", parent="parent")
    ctx.schema_svc.add_field("child", "rate", "integer")
    ctx.schema_svc.update("child", display_template="{site} {rate}")
    ctx.commit()

    ctx.schema_svc.update_field("parent", "site", new_name="place")
    ctx.commit()

    child = ctx.schema_svc.get("child")
    assert child.display_template == "{place} {rate}"
    last = _entries(ctx)[("schema", child.id)][-1]
    assert last.action == "update"
    old, new = entry_snapshots(last.old_data, last.new_data, last.delta)
    assert old["display_template"] == "{site} {rate}"
    assert new["display_template"] == "{place} {rate}"
