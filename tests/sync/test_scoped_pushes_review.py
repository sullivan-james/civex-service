"""Regressions from the independent review of hidden collections, on the
authority's side: files, answers that must not tell hidden things from absent
ones, and a re-sent change that is not news twice."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import PushAccepted, SyncEntry
from civex.testing import principal, statuses

NO_SUCH = "f" * 64


@pytest.fixture()
def world(project, authority):
    authority.schema_svc.create("encounter")
    authority.schema_svc.add_field("encounter", "site", "string")
    authority.schema_svc.add_field("encounter", "scan", "file")
    open_ = authority.dataset_svc.create("open")
    vault = authority.dataset_svc.create("vault")
    secret = authority.file_svc.store_bytes(b"secret bytes", "secret.bin")
    plain = authority.file_svc.store_bytes(b"plain bytes", "plain.bin")
    seen = authority.record_svc.add(
        "open", "encounter", {"site": "open", "scan": plain.to_dict()}
    )
    hidden = authority.record_svc.add(
        "vault", "encounter", {"site": "secret", "scan": secret.to_dict()}
    )
    authority.commit()
    perms = Permissions.of(
        p.READ,
        p.WRITE_RECORDS,
        p.ADD_FILES,
        p.NOTES,
        collections=[open_.id],
        read_collections=[open_.id],
    )
    limited = build_context(dataclasses.replace(authority.project, permissions=perms))
    yield authority, limited, open_, vault, seen, hidden, secret, plain
    limited.close()


def _create(authority, dataset, data=None, ident=None, **extra) -> SyncEntry:
    ident = ident or str(uuid.uuid4())
    return SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="record",
        entity_id=uuid.UUID(ident),
        old_data=None,
        new_data={
            "id": ident,
            "dataset_id": str(dataset.id),
            "schema_id": str(authority.schema_svc.get("encounter").id),
            "data": data or {},
            "parent_record_id": None,
            "deleted_at": None,
        },
        timestamp="2026-01-01T00:00:00+00:00",
        **extra,
    )


def _blob(ref) -> dict:
    return ref.to_dict()


# -- 1 and 12: files ------------------------------------------------------------------


def test_a_push_cannot_cite_a_file_only_a_hidden_record_holds(world):
    authority, limited, open_, vault, seen, hidden, secret, plain = world
    service = limited.authority_svc
    who = principal(limited, "limited")
    cites_secret = _create(authority, open_, {"scan": _blob(secret)})
    result = service.push(who, [cites_secret])
    assert statuses(result) == ["rejected"]
    assert result.results[0].message == p.FILE_UNAVAILABLE
    # a file a record it may read holds, or one not here yet, is fine
    ok = _create(authority, open_, {"scan": _blob(plain)})
    later = _create(authority, open_, {"scan": {**_blob(plain), "sha256": NO_SUCH}})
    assert statuses(service.push(who, [ok, later])) == ["applied", "applied"]
    # and what was refused did not make the file readable
    assert not limited.file_svc.readable(secret.sha256)


def test_a_hidden_file_is_asked_for_like_a_missing_one(world):
    authority, limited, open_, vault, seen, hidden, secret, plain = world
    service = limited.authority_svc
    assert service.missing_files([plain.sha256, secret.sha256, NO_SUCH]) == [
        secret.sha256,
        NO_SUCH,
    ]
    # the whole project's authority still knows them
    assert authority.authority_svc.missing_files([secret.sha256]) == []


# -- 16: refusing a whole action tells nothing about hidden ids ---------------------


def _answers(limited, authority, open_, vault, target_id: str):
    """One action whose second change is refused (it writes into a collection
    the device cannot read), the first being a change to `target_id`."""
    op = str(uuid.uuid4())
    first = _create(authority, open_, {"site": "x"}, ident=target_id, op=op)
    refused = _create(authority, vault, {"site": "y"}, op=op)
    return statuses(
        limited.authority_svc.push(principal(limited, "limited"), [first, refused])
    )


def test_a_refused_action_answers_a_hidden_id_as_it_does_an_absent_one(world):
    authority, limited, open_, vault, seen, hidden, secret, plain = world
    absent = _answers(limited, authority, open_, vault, str(uuid.uuid4()))
    held_hidden = _answers(limited, authority, open_, vault, str(hidden.id))
    assert held_hidden == absent == ["rejected", "rejected"]


# -- 10: a change sent again is not news twice -------------------------------------


def test_a_resent_push_is_not_announced_again(world):
    authority, limited, open_, vault, *_ = world
    who = principal(limited, "limited")
    entry = _create(authority, open_, {"site": "once"})
    first = limited.authority_svc.push(who, [entry])
    assert statuses(first) == ["applied"]
    report = PushAccepted.of(who, "someone", [entry], first)
    assert report is not None and len(report.taken) == 1
    again = limited.authority_svc.push(who, [entry])
    assert statuses(again) == ["applied"]  # the same answer, as before
    assert PushAccepted.of(who, "someone", [entry], again) is None
    # a repeat mixed with something new announces only the new
    fresh = _create(authority, open_, {"site": "new"})
    mixed = limited.authority_svc.push(who, [entry, fresh])
    report = PushAccepted.of(who, "someone", [entry, fresh], mixed)
    assert report is not None
    assert report.taken == (fresh.id,)
    assert report.counts == {"applied": 1}
