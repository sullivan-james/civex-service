"""A restore made on a device after it has seen the delete is a decision about
the delete, never a change concurrent with it: it goes in as a restore, also
for a record a server once refused (the device must not mistake it for one the
server it follows now has never had)."""

from __future__ import annotations

import pytest

from civex.testing.peers import connect, device, follow


def _open(ctx) -> list:
    return [c for c in ctx.sync_svc.conflicts() if c.status == "open"]


@pytest.mark.parametrize("refused_by", ["filling", "push"])
def test_restoring_a_pulled_delete_of_a_once_refused_record_goes_in(
    project, authority, refused_by
):
    """The call was refused by the first server (its value was not allowed
    there: when that server was filled, or when it was sent later). It reached
    the server the laptop follows now when that one was filled, so nothing
    numbered here says that server took it. A bulk delete made on that server
    is pulled, then restored here: the restore goes in, with what is beneath."""
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.schema_svc.create("selection", parent="call")
    laptop.schema_svc.add_field("selection", "n", "integer")
    laptop.dataset_svc.create("survey")
    laptop.commit()
    if refused_by == "push":
        connect(laptop)
        authority.schema_svc.update_field(
            "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
        )
        authority.commit()
    call = laptop.record_svc.add("survey", "call", {"annotation": "M (bold)"})
    for n in range(3):
        laptop.record_svc.add(
            "survey", "selection", {"n": n}, parent_record_id=str(call.id)
        )
    if refused_by == "filling":
        laptop.schema_svc.update_field(
            "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
        )
        laptop.commit()
        assert connect(laptop) == "seeded"
    else:
        laptop.commit()
        laptop.sync_svc.sync()
    assert authority.sync_repo.snapshot("record", call.id) is None
    assert any(c.kind == "rejected" for c in _open(laptop))

    # The field is opened up again, and the laptop moves to a new server,
    # filling it with everything it has.
    laptop.schema_svc.update_field("call", "annotation", restrictions={})
    laptop.commit()
    laptop.sync_svc.sync()
    server = project("server")
    follow(laptop, server, "laptop")
    assert connect(laptop, "https://server.test") == "seeded"
    assert server.sync_repo.snapshot("record", call.id) is not None

    # Deleted on that server (its own web app, one bulk delete), pulled, and
    # then restored here.
    server.record_svc.delete_many([str(call.id)])
    server.commit()
    laptop.sync_svc.sync()
    assert laptop.record_svc.find("survey", "selection") == []

    laptop.history_svc.restore_all()
    laptop.commit()
    laptop.sync_svc.sync()

    assert len(server.record_svc.find("survey", "call")) == 1
    assert len(server.record_svc.find("survey", "selection")) == 3
    assert len(laptop.record_svc.find("survey", "selection")) == 3
    assert [c.kind for c in _open(laptop)] == []


def test_a_never_taken_record_deleted_and_restored_here_still_goes_whole(
    project, authority
):
    """The server refused the call and has never had it. Deleting it here is
    numbered there (it takes nothing); restoring it here then sends the call as
    it is, as a create, rather than a restore of something not there."""
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.dataset_svc.create("survey")
    laptop.commit()
    connect(laptop)
    authority.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    authority.commit()
    call = laptop.record_svc.add("survey", "call", {"annotation": "M (bold)"})
    laptop.commit()
    laptop.sync_svc.sync()
    assert authority.sync_repo.snapshot("record", call.id) is None

    laptop.record_svc.delete(str(call.id))
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.record_svc.restore(str(call.id))
    laptop.record_svc.update(str(call.id), {"annotation": "M"})  # the fix
    laptop.commit()
    laptop.sync_svc.sync()

    assert authority.record_svc.get(str(call.id)).data["annotation"] == "M"
    assert [c.kind for c in _open(laptop)] == []


def _refused_when_filling(project, authority):
    """A laptop whose call the server refused when the laptop filled it (the
    laptop's own field did not allow the value), then opened up again here."""
    laptop = device(project, authority, "laptop")
    laptop.schema_svc.create("call")
    laptop.schema_svc.add_field("call", "annotation", "string")
    laptop.dataset_svc.create("survey")
    laptop.commit()
    call = laptop.record_svc.add("survey", "call", {"annotation": "M (bold)"})
    laptop.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    laptop.commit()
    assert connect(laptop) == "seeded"
    assert authority.sync_repo.snapshot("record", call.id) is None
    [refusal] = [c for c in _open(laptop) if c.kind == "rejected"]
    return laptop, call, refusal


def _delete_there_and_restore_here(laptop, server, call) -> None:
    server.record_svc.delete_many([str(call.id)])
    server.commit()
    laptop.sync_svc.sync()
    laptop.history_svc.restore_all()
    laptop.commit()
    laptop.sync_svc.sync()


def test_a_refusal_a_person_let_go_stays_theirs_after_a_fill(project, authority):
    """Settling a refusal is a person's: a later fill that takes the thing
    leaves it settled as they did (so it can still be undone), and the restore
    still goes in as one."""
    laptop, call, refusal = _refused_when_filling(project, authority)
    laptop.sync_svc.resolve_conflict(refusal.id, "theirs")
    laptop.commit()
    [settled] = [c for c in laptop.sync_svc.conflicts(None) if c.id == refusal.id]
    assert (settled.status, settled.resolution) == ("resolved", "theirs")

    laptop.schema_svc.update_field("call", "annotation", restrictions={})
    laptop.commit()
    laptop.sync_svc.sync()
    server = project("server")
    follow(laptop, server, "laptop")
    assert connect(laptop, "https://server.test") == "seeded"
    assert server.sync_repo.snapshot("record", call.id) is not None

    [after] = [c for c in laptop.sync_svc.conflicts(None) if c.id == refusal.id]
    assert (after.status, after.resolution) == ("resolved", "theirs")
    assert after.resolved_at == settled.resolved_at
    assert laptop.sync_repo.never_taken({("record", call.id)}) == set()

    _delete_there_and_restore_here(laptop, server, call)
    assert len(server.record_svc.find("survey", "call")) == 1
    assert [c.kind for c in _open(laptop)] == []
    assert laptop.sync_svc.reopen_conflicts([refusal.id]) == 1


def _a_reset_server(project, laptop, name):
    """The server this laptop fills, emptied (reset, or restored from before the
    upload): the same project, holding nothing. The laptop finds it so when it
    next syncs, as `sync` does after a first upload broke off."""
    server = project(name)
    server.sync_repo.set_project_id(laptop.sync_repo.meta().project_id)
    server.commit()
    follow(laptop, server, "laptop")
    return server


@pytest.mark.parametrize("again", ["taken", "refused"])
def test_filling_the_same_server_again_after_a_reset(
    project, authority, monkeypatch, again
):
    """The laptop fills the server it follows again once that server is reset
    (no other server followed, so each thing goes under the same id as before).
    Taken this time, the call is the server's: a restore goes in as one.
    Refused again after a fill had taken it, it is missing there again."""
    from civex.services import sync_service

    laptop, call, refusal = _refused_when_filling(project, authority)
    laptop.schema_svc.update_field("call", "annotation", restrictions={})
    laptop.commit()

    def fill_after_reset(name):
        server = _a_reset_server(project, laptop, name)
        # The fill breaks off before anything goes; the next sync finds the
        # server empty and fills it from the start.
        original = sync_service.SyncService._seed

        def broken(self, transport, *rest, **kw):
            def push(entries):
                raise sync_service.SyncError("connection lost", retryable=True)

            transport.push = push
            try:
                return original(self, transport, *rest, **kw)
            finally:
                del transport.push

        monkeypatch.setattr(sync_service.SyncService, "_seed", broken)
        with pytest.raises(sync_service.SyncError):
            connect(laptop, f"https://{name}.test")
        monkeypatch.setattr(sync_service.SyncService, "_seed", original)
        laptop.sync_svc.sync()
        return server

    server = fill_after_reset("server")
    assert server.sync_repo.snapshot("record", call.id) is not None
    assert laptop.sync_repo.never_taken({("record", call.id)}) == set()
    [seen] = [c for c in laptop.sync_svc.conflicts(None) if c.id == refusal.id]
    assert seen.status == "open"  # a person's to settle, as before

    if again == "taken":
        _delete_there_and_restore_here(laptop, server, call)
        assert len(server.record_svc.find("survey", "call")) == 1
        return

    laptop.schema_svc.update_field(
        "call", "annotation", restrictions={"choices": ["Y", "M", "N"]}
    )
    laptop.commit()
    server = fill_after_reset("server2")
    assert server.sync_repo.snapshot("record", call.id) is None
    assert laptop.sync_repo.never_taken({("record", call.id)}) == {call.id}
    assert any(c.kind == "rejected" and c.entity_id == call.id for c in _open(laptop))
