"""Releases travel between devices (scenarios).

`travels` makes a release on one device and checks the authority and another
device get it with its bundle of records (sent as a file, fetched when
verified), at the authority's feed number; that the authority, which keeps
everyone's files, owns the files the release cites once its bundle is there,
while the other device owns only the bundle (the authority keeps the files);
and that a withdrawal made on the second device reaches the first. `yanks`
has a device yank a release: every copy then owns nothing for it, and keeps
its tombstone. `content_is_fixed` has a device send an edit of a made
release's content hash: the authority refuses it and keeps the release as it
was. Each returns what is wrong (nothing is a pass), so a host embedding civex
can run them with its own app as the authority."""

from __future__ import annotations

from civex.testing.peers import build_study, connect, device


def _with_a_file(ctx) -> str:
    ctx.schema_svc.add_field("encounter", "photo", "file")
    photo = ctx.file_svc.store_bytes(b"a seal", "seal.jpg")
    ctx.record_svc.add("study", "encounter", {"site": "z", "photo": photo.to_dict()})
    ctx.commit()
    return photo.sha256


def _owned(ctx, name: str) -> set[str]:
    release = ctx.release_svc.get(name)
    return set(ctx.release_svc._repo.owned_pointers(release.id))


def travels(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    photo = _with_a_file(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)

    laptop.record_svc.add("study", "encounter", {"site": "y"})
    laptop.commit()
    try:
        laptop.release_svc.create("v1", "Unsynced first")
        problems.append("a release was made on a device with unsent changes")
    except Exception:
        pass
    laptop.rollback()
    laptop.sync_svc.sync()
    made = laptop.release_svc.create(
        "v1", "Seal survey", authors=[{"name": "Ada Lovelace"}]
    )
    laptop.commit()
    if made.feed_seq is None:
        problems.append("the release on a synced device has no feed number")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    phone.sync_svc.sync()

    for name, ctx in (("authority", authority), ("phone", phone)):
        try:
            theirs = ctx.release_svc.get("v1")
        except Exception:
            problems.append(f"the {name} has no release v1")
            continue
        if theirs.content_hash != made.content_hash:
            problems.append(f"the {name}'s release has another content hash")
        if theirs.local_seq is not None:
            problems.append(f"the {name} took the laptop's own history position")
    if not authority.file_svc.exists(made.bundle_sha256):
        problems.append("the authority never got the release's bundle")
    if _owned(laptop, "v1") != {photo, made.bundle_sha256}:
        problems.append("the laptop's release does not own its files and bundle")
    if _owned(authority, "v1") != {photo, made.bundle_sha256}:
        problems.append("the authority's release does not own the files it cites")
    if _owned(phone, "v1") != {made.bundle_sha256}:
        problems.append("the phone's release owns more than its bundle")
    if phone.file_svc.exists(made.bundle_sha256):
        problems.append("the phone fetched the bundle before anyone asked for it")
    if not phone.release_svc.verify("v1").matches:
        problems.append("the phone could not verify the release")
    if phone.release_svc.changes_since("v1").by != "feed":
        problems.append("the phone did not compare by the server's numbers")

    phone.release_svc.withdraw("v1", "calibration error")
    phone.commit()
    phone.sync_svc.sync()
    laptop.sync_svc.sync()
    if laptop.release_svc.get("v1").withdrawn_reason != "calibration error":
        problems.append("the laptop never saw the release withdrawn")
    return problems


def yanks(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    _with_a_file(laptop)
    connect(laptop)
    laptop.release_svc.create("v1", "Seal survey")
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    if not _owned(authority, "v1"):
        problems.append("the authority's release owns nothing before the yank")
    laptop.release_svc.yank("v1", "consent withdrawn")
    laptop.commit()
    laptop.sync_svc.sync()
    for name, ctx in (("laptop", laptop), ("authority", authority)):
        release = ctx.release_svc.get("v1")
        if release.yanked_reason != "consent withdrawn":
            problems.append(f"the {name} does not have the release yanked")
        if _owned(ctx, "v1"):
            problems.append(f"the {name}'s yanked release still owns files")
    return problems


def content_is_fixed(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    connect(laptop)
    made = laptop.release_svc.create("v1", "Seal survey")
    laptop.commit()
    laptop.sync_svc.sync()

    # A device whose copy was changed behind civex's back sends the change.
    repo = laptop.release_svc._repo
    tampered = repo.update(made.id, content_hash="sha256:" + "0" * 64)
    laptop.audit_svc.log_change(
        "update", "release", made.id, made.to_dict(), tampered.to_dict()
    )
    laptop.commit()
    laptop.sync_svc.sync()
    if authority.release_svc.get("v1").content_hash != made.content_hash:
        problems.append("the authority took a change to a release's content")
    if not laptop.sync_svc.conflicts():
        problems.append("the laptop was not told its change was refused")
    return problems
