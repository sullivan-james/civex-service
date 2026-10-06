"""A synced change says who made it (the name chosen on the device, as given)
and which device it came through (stamped by the authority from the token)."""

from __future__ import annotations

from sqlalchemy import text

from .peers import connect


def _named(ctx, name):
    ctx.audit_svc._actor = name  # what `[identity] name` sets for this project
    return ctx


def _last(ctx, record):
    row = ctx._session.execute(
        text(
            "SELECT actor, device FROM audit_log WHERE entity_id = :i "
            "ORDER BY local_seq DESC LIMIT 1"
        ),
        {"i": record.id.hex},
    ).one()
    return tuple(row)


def test_the_author_is_kept_and_the_device_stamped(pair, authority):
    laptop, phone, record = pair
    _named(laptop, "l2")
    laptop.record_svc.update(str(record.id), {"site": "by l2", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    assert _last(authority, record) == ("l2", "laptop")
    assert _last(laptop, record) == ("l2", "laptop")  # its own copy learns it
    assert _last(phone, record) == ("l2", "laptop")
    entry = authority.history_svc.page(entity_id=record.id, sort="-timestamp")[0]
    assert (entry.actor, entry.device) == ("l2", "laptop")


def test_a_device_cannot_write_as_the_server(pair, authority):
    laptop, _, record = pair
    _named(laptop, "sync")
    laptop.record_svc.update(str(record.id), {"site": "sneaky", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    assert _last(authority, record) == ("laptop", "laptop")


def test_a_change_made_on_the_server_has_no_device(project, authority):
    from .peers import build_study, device

    laptop = device(project, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    authority.record_svc.update(str(record.id), {"site": "here", "depth": 1.0})
    authority.commit()
    assert _last(authority, record)[1] is None
