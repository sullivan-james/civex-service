"""A device knows which of its files the server holds: what it has said it has,
remembered (`server_files`), so it can say which aren't there yet, ask only
about those, and show sending as it goes."""

from __future__ import annotations

from civex.domain.sync import SENDING

from .peers import build_study, connect, device


def _with_file(ctx, record, content: bytes):
    ctx.schema_svc.add_field("encounter", "scan", "file")
    ctx.commit()
    ref = ctx.file_svc.store_bytes(content, "scan.bin")
    ctx.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    ctx.commit()
    return ref


def _location(ctx, record):
    return ctx.record_svc.get(str(record.id)).data["scan"]["location"]


def test_a_file_waits_to_be_sent_until_the_server_has_it(pair):
    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    assert laptop.sync_svc.status().files_to_send == 1
    assert _location(laptop, record)["sent"] is False

    laptop.sync_svc.sync()

    assert laptop.sync_svc.status().files_to_send == 0
    assert "sent" not in _location(laptop, record)


def test_sending_is_shown_as_it_goes(pair):
    laptop, _, record = pair
    content = b"x" * 300_000
    _with_file(laptop, record, content)
    seen = []
    laptop.sync_svc.sync(progress=seen.append)

    sending = [p for p in seen if p.phase == SENDING]
    assert sending[0].done == 0 and sending[0].total == 1
    assert sending[-1].done == 1 and sending[-1].bytes_done == len(content)


def test_files_the_server_holds_are_not_asked_about_again(pair):
    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    calls = laptop._holder["inner"].calls
    calls.clear()

    laptop.sync_svc.sync(check_files=False)  # a background sync
    assert "missing_files" not in calls

    laptop.sync_svc.sync()  # asked for: every file is checked again
    assert "missing_files" in calls


def test_a_file_that_cant_be_read_stays_not_sent(pair):
    laptop, _, record = pair
    ref = _with_file(laptop, record, b"the scan")
    laptop.file_svc.local_path(ref.sha256).unlink()  # as if its drive were unplugged
    laptop.sync_svc.sync()

    assert laptop.sync_svc.status().files_to_send == 1


def test_a_file_downloaded_from_the_server_is_known_to_be_there(pair):
    laptop, phone, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    phone.commit()

    assert phone.sync_svc.status().files_to_send == 0
    assert "sent" not in _location(phone, record)


def test_following_another_server_forgets_what_the_old_one_held(pair):
    """`forget_numbers` is what connecting to a different authority calls."""
    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    assert laptop.sync_svc.status().files_to_send == 0

    laptop.sync_repo.forget_numbers()
    assert laptop.sync_svc.status().files_to_send == 1


def test_a_project_that_doesnt_sync_says_nothing_about_the_server(project, authority):
    lonely = device(project, authority, "lonely")
    record = build_study(lonely)
    _with_file(lonely, record, b"the scan")
    assert lonely.sync_svc.status().files_to_send == 0
    assert "sent" not in _location(lonely, record)
    connect(lonely)
    assert lonely.sync_svc.status().files_to_send == 0  # connecting sent it
