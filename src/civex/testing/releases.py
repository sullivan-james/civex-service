"""Releases travel between devices (scenarios).

`travels` makes a release on one device and checks the authority and another
device get it with its bundle (sent as a file, fetched when verified), at the
authority's feed number, and that a withdrawal made on the second device
reaches the first. `content_is_fixed` has a device send an edit of a made
release's content hash: the authority refuses it and keeps the release as it
was. Each returns what is wrong (nothing is a pass), so a host embedding civex
can run them with its own app as the authority."""

from __future__ import annotations

from civex.testing.peers import build_study, connect, device


def travels(project, authority) -> list[str]:
    problems: list[str] = []
    laptop = device(project, authority, "laptop")
    build_study(laptop)
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
    made = laptop.release_svc.create("v1", "Seal survey", authors=["Ada Lovelace"])
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
