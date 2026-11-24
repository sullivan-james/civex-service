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
