"""Structure changes need unrestricted read, and deleting a field needs the
right to delete: one rule in `Permissions`, so the services, the data API and a
pushed change all meet it. Deleting a collection (or making it local) respects
records the caller cannot see that point into it. On a clone the person can
still do anything: this is the server's judgement on a push."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.permissions import Permissions
from civex.domain.sync import SyncEntry
from civex.testing import principal, statuses
from civex.testing.peers import join, wire

C1, C2 = uuid.uuid4(), uuid.uuid4()
STRUCTURE = (
    ("schema", "create"),
    ("schema", "update"),
    ("field", "create"),
    ("field", "update"),
    ("field", "restore"),
    ("dataset", "create"),
    ("dataset", "update"),
    ("dataset", "restore"),
)


def _entry(kind, action, entity_id=None, snapshot=None) -> SyncEntry:
    entity_id = entity_id or uuid.uuid4()
    snapshot = snapshot or {"id": str(entity_id)}
    gone = action in ("delete", "purge")
    return SyncEntry(
        id=uuid.uuid4(),
        action=action,
        entity_type=kind,
        entity_id=entity_id,
        old_data=snapshot if gone else None,
        new_data=None if gone else snapshot,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_structure_is_unavailable_to_anyone_who_cannot_read_everything():
    for restricted in (
        Permissions.of(p.READ, p.CHANGE_STRUCTURE, read_collections=[C1]),
        Permissions.of(p.READ, p.CHANGE_STRUCTURE).without([p.READ], [C1]),
        Permissions.of(p.READ, p.CHANGE_STRUCTURE, read_collections=[]),
    ):
        assert not restricted.can(p.CHANGE_STRUCTURE)
        assert not restricted.can_somewhere(p.CHANGE_STRUCTURE)
        assert not restricted.can(p.CHANGE_STRUCTURE, C1)
        with pytest.raises(NotAllowedError):
            restricted.require(p.CHANGE_STRUCTURE)
        for kind, action in STRUCTURE:
            assert restricted.refuses(None, _entry(kind, action)), (kind, action)
        # carving more out, or round-tripping it, never gives it back
        assert not restricted.lacking(p.NOTES).can(p.CHANGE_STRUCTURE)
        assert not Permissions.from_dict(restricted.to_dict()).can(p.CHANGE_STRUCTURE)
    whole = Permissions.of(p.READ, p.CHANGE_STRUCTURE)
    assert whole.can(p.CHANGE_STRUCTURE)
    for kind, action in STRUCTURE:
        assert whole.refuses(None, _entry(kind, action)) is None, (kind, action)
    assert Permissions.everything().can(p.CHANGE_STRUCTURE)


def test_deleting_a_field_takes_the_right_to_delete_too():
    assert p.action_for(_entry("field", "delete")) == (p.DELETE, None)
    assert p.action_for(_entry("field", "purge")) == (p.DELETE, None)
    for action in ("delete", "purge"):
        entry = _entry("field", action)
        structure_only = Permissions.of(p.READ, p.CHANGE_STRUCTURE)
        assert structure_only.refuses(None, entry)
        assert Permissions.of(p.READ, p.DELETE).refuses(None, entry)
        assert (
            Permissions.of(p.READ, p.DELETE, p.CHANGE_STRUCTURE).refuses(None, entry)
            is None
        )


@pytest.fixture()
def world(project, authority):
    authority.schema_svc.create("encounter")
    authority.schema_svc.add_field("encounter", "site", "string")
    open_ = authority.dataset_svc.create("open")
    vault = authority.dataset_svc.create("vault")
    authority.commit()
    contexts = []

    def limited(perms):
        ctx = build_context(dataclasses.replace(authority.project, permissions=perms))
        contexts.append(ctx)
        return ctx

    yield authority, limited, open_, vault
    for ctx in contexts:
        ctx.close()


def test_services_refuse_structure_to_a_limited_reader(world):
    authority, limited, open_, vault = world
    ctx = limited(
        Permissions.of(
            p.READ, p.WRITE_RECORDS, p.CHANGE_STRUCTURE, read_collections=[open_.id]
        )
    )
    for call in (
        lambda: ctx.schema_svc.create("other"),
        lambda: ctx.schema_svc.add_field("encounter", "x", "string"),
        lambda: ctx.schema_svc.update_field("encounter", "site", required=True),
        lambda: ctx.schema_svc.update("encounter", description="new"),
        lambda: ctx.dataset_svc.create("third"),
        lambda: ctx.dataset_svc.update("open", description="new"),
    ):
        with pytest.raises(NotAllowedError):
            call()


def test_deleting_a_field_in_the_service_needs_delete(world):
    authority, limited, open_, vault = world
    ctx = limited(Permissions.of(p.READ, p.CHANGE_STRUCTURE))
    with pytest.raises(NotAllowedError):
        ctx.schema_svc.delete_field("encounter", "site")
    ctx = limited(Permissions.of(p.READ, p.CHANGE_STRUCTURE, p.DELETE))
    ctx.schema_svc.delete_field("encounter", "site")


def _entries(project, authority, make, name="clone"):
    """What a person with every right does on their own clone (nothing blocks
    it there), as the entries the clone would send."""
    clone = project(name)
    join(authority, clone)
    make(clone)
    clone.commit()
    return [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in clone.sync_repo.pending_entries(1000)
    ]


CHANGES = {
    "new kind": lambda c: c.schema_svc.create("newkind"),
    "rename kind": lambda c: c.schema_svc.update("encounter", new_name="visit"),
    "new field": lambda c: c.schema_svc.add_field("encounter", "z", "string"),
    "change field": lambda c: c.schema_svc.update_field(
        "encounter", "site", required=True
    ),
    "new collection": lambda c: c.dataset_svc.create("third"),
    "change collection": lambda c: c.dataset_svc.update("open", description="new"),
}


@pytest.mark.parametrize("what", CHANGES)
def test_a_push_of_structure_needs_unrestricted_read(world, project, what):
    authority, limited, open_, vault = world
    entries = _entries(project, authority, CHANGES[what])
    assert entries
    restricted = limited(
        Permissions.of(
            p.READ,
            p.WRITE_RECORDS,
            p.CHANGE_STRUCTURE,
            p.DELETE,
            read_collections=[open_.id],
        )
    )
    result = restricted.authority_svc.push(principal(restricted, "dev"), entries)
    restricted.commit()
    assert set(statuses(result)) == {"rejected"}, what
    # the same entries from someone who reads everything go in
    # (a change a device sent is answered the same when sent again, so these are
    # the same change made again, with new ids)
    entries = _entries(project, authority, CHANGES[what], "clone2")
    whole = limited(Permissions.of(p.READ, p.WRITE_RECORDS, p.CHANGE_STRUCTURE))
    result = whole.authority_svc.push(principal(whole, "dev2"), entries)
    whole.commit()
    assert set(statuses(result)) == {"applied"}, [r.message for r in result.results]


def test_a_pushed_field_delete_needs_the_right_to_delete(world, project):
    authority, limited, open_, vault = world
    entries = _entries(
        project, authority, lambda c: c.schema_svc.delete_field("encounter", "site")
    )
    assert any(e.entity_type == "field" and e.action == "delete" for e in entries)
    structure_only = limited(Permissions.of(p.READ, p.CHANGE_STRUCTURE))
    result = structure_only.authority_svc.push(principal(structure_only, "a"), entries)
    structure_only.commit()
    assert "applied" not in statuses(result)
    authority.commit()
    assert any(f.name == "site" for f in authority.schema_svc.get("encounter").fields)
    entries = _entries(
        project,
        authority,
        lambda c: c.schema_svc.delete_field("encounter", "site"),
        "clone2",
    )
    both = limited(Permissions.of(p.READ, p.CHANGE_STRUCTURE, p.DELETE))
    result = both.authority_svc.push(principal(both, "b"), entries)
    both.commit()
    assert set(statuses(result)) == {"applied"}
    authority.commit()
    assert not any(
        f.name == "site" for f in authority.schema_svc.get("encounter").fields
    )


def test_release_follows_the_structure_rule_however_the_permissions_were_built():
    restricted = Permissions.of(p.READ, p.CHANGE_STRUCTURE, read_collections=[C1])
    for same in (
        restricted,
        restricted.lacking(p.NOTES),
        Permissions.from_dict(restricted.to_dict()),
    ):
        assert not same.can(p.CHANGE_STRUCTURE) and not same.can(p.RELEASE)


def _global_with_hidden_referrer(authority):
    shared = authority.dataset_svc.create("shared", scope="global")
    authority.schema_svc.add_field(
        "encounter", "friend", "reference", restrictions={"schema": "encounter"}
    )
    target = authority.record_svc.add("shared", "encounter", {"site": "t"})
    authority.record_svc.add(
        "vault", "encounter", {"site": "points", "friend": str(target.id)}
    )
    authority.commit()
    return shared


def test_deleting_or_localising_a_collection_respects_hidden_referrers(world):
    authority, limited, open_, vault = world
    shared = _global_with_hidden_referrer(authority)
    ctx = limited(Permissions.of(p.READ, p.DELETE, read_collections=[shared.id]))
    with pytest.raises(ValidationError, match="cannot see"):
        ctx.dataset_svc.delete("shared")
    # making it local is structure, refused to a limited reader outright; the
    # referrer check behind it is the same one, kept as a second line
    with pytest.raises(NotAllowedError):
        ctx.dataset_svc.update("shared", scope="local")
    with pytest.raises(ValidationError, match="cannot see"):
        ctx.dataset_svc._check_not_referenced(shared, "make local")
    authority.commit()
    assert authority.dataset_svc.get("shared").scope == "global"
    # someone who sees everything is told what points at it, as before
    with pytest.raises(ValidationError, match="reference it"):
        authority.dataset_svc.delete("shared")


# -- pushes that would leave references dangling or break structure ---------------


def _push(limited, perms, entries, name):
    ctx = limited(perms)
    result = ctx.authority_svc.push(principal(ctx, name), entries)
    ctx.commit()
    return result


def _refs_world(authority, *, referrer_in="vault"):
    """A global collection `shared` whose record `target` a record in
    `referrer_in` points at (None: no referrer, the control)."""
    shared = authority.dataset_svc.create("shared", scope="global")
    authority.schema_svc.add_field(
        "encounter", "friend", "reference", restrictions={"schema": "encounter"}
    )
    target = authority.record_svc.add("shared", "encounter", {"site": "t"})
    if referrer_in:
        authority.record_svc.add(
            referrer_in, "encounter", {"site": "p", "friend": str(target.id)}
        )
    authority.commit()
    return shared, target


def _forced_clone(project, authority, target, name):
    """A clone that force-deleted the target (clearing what pointed at it) and
    then sent that: the cleared references are not in what is pushed next."""
    clone = project(name)
    join(authority, clone)
    clone.record_svc.delete(str(target.id), force=True)
    clone.commit()
    first = [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in clone.sync_repo.pending_entries(1000)
    ]
    clone.sync_repo.mark_all_synced()
    clone.commit()
    return clone, first


def _pending(clone):
    clone.commit()
    return [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in clone.sync_repo.pending_entries(1000)
    ]


def _deleter(open_, shared):
    return Permissions.of(
        p.READ, p.WRITE_RECORDS, p.DELETE, read_collections=[open_.id, shared.id]
    )


@pytest.mark.parametrize("referrer_in", ["vault", None])
def test_a_pushed_record_delete_respects_hidden_referrers(world, project, referrer_in):
    authority, limited, open_, vault = world
    shared, target = _refs_world(authority, referrer_in=referrer_in)
    _, first = _forced_clone(project, authority, target, "clone")
    only = [e for e in first if e.entity_id == target.id]
    assert only and only[0].action == "delete"
    result = _push(limited, _deleter(open_, shared), only, "a")
    expected = "rejected" if referrer_in else "applied"
    assert set(statuses(result)) == {expected}
    authority.commit()
    gone = authority.record_svc._records.get_by_prefix(
        str(target.id), include_deleted=True
    )
    assert (gone.deleted_at is not None) == (referrer_in is None)


@pytest.mark.parametrize("referrer_in", ["vault", None])
def test_deleting_the_referenced_records_first_does_not_get_past_the_collection_check(
    world, project, referrer_in
):
    authority, limited, open_, vault = world
    shared, target = _refs_world(authority, referrer_in=referrer_in)
    clone, first = _forced_clone(project, authority, target, "clone")
    clone.dataset_svc.delete("shared")
    second = _pending(clone)
    assert any(e.entity_type == "dataset" and e.action == "delete" for e in second)
    perms = _deleter(open_, shared)
    one = _push(limited, perms, [e for e in first if e.entity_id == target.id], "a")
    two = _push(limited, perms, second, "b")
    expected = "rejected" if referrer_in else "applied"
    assert expected in statuses(two) or not referrer_in
    if referrer_in:
        assert set(statuses(one)) == {"rejected"}
        assert "applied" not in statuses(two)
        authority.commit()
        assert authority.dataset_svc.get("shared").deleted_at is None
    else:
        assert set(statuses(two)) == {"applied"}


@pytest.mark.parametrize("change", ["delete", "local"])
@pytest.mark.parametrize("referrer_in", ["open", None])
def test_a_full_reader_cannot_push_a_collection_away_from_its_referrers(
    world, project, change, referrer_in
):
    authority, limited, open_, vault = world
    shared, target = _refs_world(authority, referrer_in=referrer_in)
    clone, _ = _forced_clone(project, authority, target, "clone")
    if change == "delete":
        clone.dataset_svc.delete("shared")
    else:
        clone.dataset_svc.update("shared", scope="local")
    entries = _pending(clone)
    assert any(e.entity_type == "dataset" for e in entries)
    perms = Permissions.of(p.READ, p.WRITE_RECORDS, p.DELETE, p.CHANGE_STRUCTURE)
    result = _push(limited, perms, entries, "a")
    authority.commit()
    if referrer_in:
        kept = authority.dataset_svc.get("shared")
        assert "applied" not in statuses(result)
        assert kept.deleted_at is None and kept.scope == "global"
    else:
        assert set(statuses(result)) == {"applied"}


def _lifecycle(authority, kind):
    if kind == "dataset restore" or kind == "dataset purge":
        authority.dataset_svc.create("scratch")
        authority.dataset_svc.delete("scratch")
    elif kind == "schema restore" or kind == "schema purge":
        authority.schema_svc.create("scratch")
        authority.schema_svc.delete("scratch")
    else:
        authority.schema_svc.delete_field("encounter", "site")
    authority.commit()


LIFECYCLE = {
    "dataset restore": lambda c: c.dataset_svc.restore("scratch"),
    "dataset purge": lambda c: c.dataset_svc.purge("scratch"),
    "schema restore": lambda c: c.schema_svc.restore("scratch"),
    "schema purge": lambda c: c.schema_svc.purge("scratch"),
    "field restore": lambda c: c.schema_svc.restore_field(
        "encounter",
        next(
            f.id
            for f in c.schema_svc._repo.get_by_name(
                "encounter", include_deleted=True
            ).deleted_fields
            if f.name == "site"
        ),
    ),
}


@pytest.mark.parametrize("kind", LIFECYCLE)
def test_restoring_or_purging_structure_follows_the_same_rule(world, project, kind):
    authority, limited, open_, vault = world
    _lifecycle(authority, kind)
    entries = _entries(project, authority, LIFECYCLE[kind], "c1")
    assert entries
    restricted = Permissions.of(
        p.READ, p.DELETE, p.CHANGE_STRUCTURE, read_collections=[open_.id]
    )
    result = _push(limited, restricted, entries, "a")
    assert "applied" not in statuses(result), kind
    entries = _entries(project, authority, LIFECYCLE[kind], "c2")
    whole = Permissions.of(p.READ, p.DELETE, p.CHANGE_STRUCTURE)
    result = _push(limited, whole, entries, "b")
    assert set(statuses(result)) == {"applied"}, (kind, result)


def test_an_explicit_release_grant_is_withheld_from_a_restricted_reader():
    for restricted in (
        Permissions.of(p.READ, p.RELEASE, read_collections=[C1]),
        Permissions.of(p.READ, p.RELEASE).without([p.READ], [C1]),
    ):
        assert not restricted.can(p.RELEASE)
        assert not restricted.lacking(p.NOTES).can(p.RELEASE)
    assert Permissions.of(p.READ, p.RELEASE).can(p.RELEASE)


@pytest.mark.parametrize("action", ["restore", "create"])
def test_no_action_name_gets_a_collection_made_local_past_its_referrers(
    world, project, action
):
    authority, limited, open_, vault = world
    shared, target = _refs_world(authority, referrer_in="open")
    clone, _ = _forced_clone(project, authority, target, "clone")
    clone.dataset_svc.update("shared", scope="local")
    entries = [
        dataclasses.replace(e, action=action) if e.entity_type == "dataset" else e
        for e in _pending(clone)
    ]
    assert any(e.entity_type == "dataset" and e.action == action for e in entries)
    perms = Permissions.of(p.READ, p.WRITE_RECORDS, p.DELETE, p.CHANGE_STRUCTURE)
    result = _push(limited, perms, entries, "a")
    authority.commit()
    assert "applied" not in statuses(result)
    assert authority.dataset_svc.get("shared").scope == "global"


def _answers(result):
    return [(r.status, r.message) for r in result.results]


def _absent(entry):
    gone = uuid.uuid4()
    old = {**(entry.old_data or {}), "id": str(gone)}
    return dataclasses.replace(entry, id=uuid.uuid4(), entity_id=gone, old_data=old)


def _one_action(entries, op="one"):
    """The entries as one action, each with an id of its own this time."""
    return [dataclasses.replace(e, id=uuid.uuid4(), op=op) for e in entries]


def test_a_hidden_record_in_an_action_answers_as_an_absent_one(world, project):
    authority, limited, open_, vault = world
    shared, target = _refs_world(authority)
    ((hidden, _),) = authority.record_svc._find_referrers({target.id}, set())
    clone = project("clone")
    join(authority, clone)
    clone.record_svc.delete(str(hidden.id))
    clone.record_svc.delete(str(target.id))
    entries = _pending(clone)
    (gone,) = [e for e in entries if e.entity_id == hidden.id]
    (tgt,) = [e for e in entries if e.entity_id == target.id]
    perms = _deleter(open_, shared)
    # the guess is right (the hidden record) or wrong (nothing there): the
    # same answer, so a refusal cannot tell which
    right = _push(limited, perms, _one_action([gone, tgt], "a"), "a")
    wrong = _push(limited, perms, _one_action([_absent(gone), tgt], "b"), "a")
    assert _answers(right) == _answers(wrong)
    assert "applied" not in statuses(right)


def test_a_hidden_record_does_not_change_which_other_refusal_is_given(world, project):
    authority, limited, open_, vault = world
    hidden = authority.record_svc.add("vault", "encounter", {"site": "h"})
    authority.commit()
    clone = project("clone")
    join(authority, clone)
    clone.record_svc.delete(str(hidden.id))
    (gone,) = _pending(clone)
    bad = _entries(project, authority, CHANGES["new field"], "c2")
    perms = Permissions.of(
        p.READ, p.WRITE_RECORDS, p.DELETE, read_collections=[open_.id]
    )
    answers = []
    for name, first in (("a", gone), ("b", _absent(gone))):
        batch = _one_action([first, *bad], name)
        answers.append(_answers(_push(limited, perms, batch, "a")))
    assert answers[0] == answers[1]
