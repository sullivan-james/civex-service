"""Releases never travel between devices (scenarios).

A release is published on a host and kept there; it is never made on, sent by
or fed to a device. `stay_where_made` makes a release on a device and on the
authority and checks that neither reaches the other, that a release is no
unsent change, and that the release made on a computer stays readable and
keeps its files. `refused_when_sent` has a device that does not know that (a
protocol 5 one) send a release: the authority refuses it with its own code and
keeps nothing. Each returns what is wrong (nothing is a pass), so a host
embedding civex can run them with its own app as the authority."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from civex.domain.sync import REFUSAL_NOT_SYNCED, REJECTED, SyncEntry
from civex.testing.peers import build_study, connect, device, principal


def _with_a_file(ctx) -> str:
    ctx.schema_svc.add_field("encounter", "photo", "file")
    photo = ctx.file_svc.store_bytes(b"a seal", "seal.jpg")
    ctx.record_svc.add("study", "encounter", {"site": "z", "photo": photo.to_dict()})
    ctx.commit()
    return photo.sha256


def stay_where_made(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    photo = _with_a_file(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()

    made = laptop.release_svc.create("v1", "Seal survey")
    laptop.commit()
    if laptop.sync_svc.status().pending:
        problems.append("a release counts as a change not yet sent")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    phone.sync_svc.sync()
    if any(r.name == "v1" for r in authority.release_svc.list_all()):
        problems.append("the authority was sent a release")
    if any(r.name == "v1" for r in phone.release_svc.list_all()):
        problems.append("the phone was given a release")
    if authority.file_svc.exists(made.bundle_sha256):
        problems.append("a release's bundle was sent to the authority")
    if photo not in set(laptop.release_svc._repo.owned_pointers(made.id)):
        problems.append("the laptop's release stopped keeping its files")
    if not laptop.release_svc.verify("v1").matches:
        problems.append("the laptop could not verify its own release")

    # What the authority publishes is its own: no device is fed it.
    authority.release_svc.create("v2", "Published here")
    authority.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    for name, ctx in (("laptop", laptop), ("phone", phone)):
        if any(r.name == "v2" for r in ctx.release_svc.list_all()):
            problems.append(f"the {name} was fed the authority's release")
    fed, _ = authority.sync_repo.entries_after(0, 1000)
    if any(e.entity_type == "release" for e in fed):
        problems.append("the authority's feed carries a release")
    return problems


def refused_when_sent(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    made = laptop.release_svc.create("v1", "Seal survey")
    laptop.commit()
    entry = SyncEntry(
        id=uuid.uuid4(),
        action="create",
        entity_type="release",
        entity_id=made.id,
        old_data=None,
        new_data={
            k: v for k, v in made.to_dict().items() if k not in ("local_seq", "indexed")
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    result = authority.authority_svc.push(principal(authority, "laptop"), [entry])
    authority.commit()
    (answer,) = result.results
    if answer.status != REJECTED:
        problems.append(f"a pushed release was {answer.status}, not refused")
    codes = [c.get("code") for c in answer.conflicts]
    if codes != [REFUSAL_NOT_SYNCED]:
        problems.append(f"the refusal had the codes {codes}")
    if authority.release_svc.list_all():
        problems.append("the authority kept a release it refused")
    return problems
