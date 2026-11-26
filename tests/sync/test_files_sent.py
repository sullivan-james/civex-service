"""A device knows which of its files the server holds: what it has said it has,
remembered (`server_files`), so it can say which aren't there yet, ask only
about those, and show sending as it goes."""

from __future__ import annotations

from civex.domain.sync import SENDING

from civex.testing.peers import build_study, connect, device


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
    assert laptop.sync_svc.status().files_to_send == 1  # a sync moves records only
    laptop.sync_svc.send_files()

    assert laptop.sync_svc.status().files_to_send == 0
    assert _location(laptop, record)["sent"] is True


def test_sending_is_shown_as_it_goes(pair):
    laptop, _, record = pair
    content = b"x" * 300_000
    _with_file(laptop, record, content)
    seen = []
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files(progress=seen.append)

    sending = [p for p in seen if p.phase == SENDING]
    assert sending[0].done == 0 and sending[0].total == 1
    assert sending[0].bytes_total == len(content)  # how much, before any goes
    assert sending[-1].done == 1 and sending[-1].bytes_done == len(content)


def test_files_the_server_holds_are_not_asked_about_again(pair):
    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    calls = laptop._holder["inner"].calls
    calls.clear()

    laptop.sync_svc.send_files()  # a background pass
    laptop.sync_svc.sync()  # a sync never asks about files
    assert "missing_files" not in calls

    laptop.sync_svc.send_files(everything=True)  # every file checked again
    assert "missing_files" in calls


def test_a_file_that_cant_be_read_stays_not_sent(pair):
    laptop, _, record = pair
    ref = _with_file(laptop, record, b"the scan")
    laptop.file_svc.local_path(ref.sha256).unlink()  # as if its drive were unplugged
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()

    assert laptop.sync_svc.status().files_to_send == 1


def test_a_file_downloaded_from_the_server_is_known_to_be_there(pair):
    laptop, phone, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    phone.commit()

    assert phone.sync_svc.status().files_to_send == 0
    assert _location(phone, record)["sent"] is True


def test_following_another_server_forgets_what_the_old_one_held(pair):
    """`forget_numbers` is what connecting to a different authority calls."""
    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
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
    # Connecting filled the server with the records; the file goes apart.
    assert lonely.sync_svc.status().files_to_send == 1
    lonely.sync_svc.send_files()
    assert lonely.sync_svc.status().files_to_send == 0


def test_files_waiting_say_why_they_havent_gone(pair):
    laptop, _, record = pair
    ref = _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    waiting = laptop.sync_svc.status().files_waiting
    assert waiting is not None
    assert (waiting.ready, waiting.offline) == (1, [])

    # Not on this computer at all (lost here, say): nothing is stored for it,
    # so it is not this computer's to send, and nothing says it is missing
    # until the server is asked.
    laptop.file_svc._store.delete(ref.sha256)
    laptop.commit()
    assert laptop.sync_svc.status().files_waiting is None
    assert _location(laptop, record)["state"] == "remote"
    laptop.sync_svc.missing_files(with_groups=False)  # asks: not there either
    laptop.config.sync.arriving_hours = 0
    status = laptop.sync_svc.status()
    assert status.files_waiting is None and status.files_to_send == 0
    assert (status.files_arriving, status.files_missing) == (0, 1)
    location = _location(laptop, record)
    assert (location["state"], location["sent"]) == ("absent", False)
    # Which computer added it, by the name the server knows it by (never the
    # person's name, as if it were a computer).
    assert location["reason"] == (
        "It isn't on this computer, and the server hasn't got it. "
        "It was added on 'laptop'."
    )

    laptop.sync_repo.confirm_on_server([ref.sha256])
    assert laptop.sync_svc.status().files_missing == 0


def test_each_pass_sends_a_file_and_the_next_asks_only_about_the_rest(
    pair, monkeypatch
):
    import civex.services.sync_service as sync_service

    laptop, _, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    sync = laptop.sync_svc
    laptop.sync_svc.sync()
    refs = [laptop.file_svc.store_bytes(bytes([i]) * 50, f"f{i}.bin") for i in range(3)]
    for i, ref in enumerate(refs):
        laptop.record_svc.add(
            "study", "encounter", {"site": str(i), "scan": ref.to_dict()}
        )
    laptop.commit()
    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 1)
    transport = sync._transport()
    real = transport.missing_files
    asked = []

    def spy(shas):
        asked.append(list(shas))
        return real(shas)

    monkeypatch.setattr(transport, "missing_files", spy)
    monkeypatch.setattr(sync, "_transport", lambda: transport)
    passes = []
    for _ in range(5):
        asked.clear()
        report = sync.send_files(seconds=0.0)
        passes.append((report.sent, report.stopped, len(asked)))
        if not report.stopped:
            break
    assert all(sent >= 1 for sent, _, _ in passes[:-1])
    assert sync.status().files_to_send == 0
    assert sum(sent for sent, _, _ in passes) == 3
    # Later passes ask about fewer files, not all of them again.
    assert passes[-1][2] <= passes[0][2]


def test_a_slow_check_does_not_use_up_the_pass_before_a_file_goes(pair, monkeypatch):
    """Asking which files the server lacks can outlast the time a pass has;
    the pass still uploads a file, and the next one carries on after the pages
    already settled instead of asking about everything again."""
    import civex.services.sync_service as sync_service

    laptop, _, record = pair
    _with_file(laptop, record, b"the scan")
    laptop.sync_svc.sync()
    transport = laptop.sync_svc._transport()
    real = transport.missing_files
    asked = []

    def slow(shas):
        asked.append(list(shas))
        sync_service.time.sleep(0.05)
        return real(shas)

    monkeypatch.setattr(transport, "missing_files", slow)
    monkeypatch.setattr(laptop.sync_svc, "_transport", lambda: transport)
    report = laptop.sync_svc.send_files(seconds=0.0)
    assert report.sent == 1
    assert laptop.sync_svc.status().files_to_send == 0


def test_files_that_cannot_be_read_here_do_not_keep_the_rest_from_going(
    pair, monkeypatch
):
    """Hash order puts them first every pass; a pass that stops carries on
    after where it got to, so the readable ones further along are reached."""
    import civex.services.sync_service as sync_service

    laptop, _, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    sync = laptop.sync_svc
    sync.sync()
    refs = [laptop.file_svc.store_bytes(bytes([i]) * 40, f"f{i}.bin") for i in range(8)]
    for i, ref in enumerate(refs):
        laptop.record_svc.add(
            "study", "encounter", {"site": str(i), "scan": ref.to_dict()}
        )
    laptop.commit()
    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 2)
    unreadable = sorted(r.sha256 for r in refs)[:5]
    store = object.__getattribute__(sync, "_svc")._files
    real = store.open

    def opening(sha):
        if sha in unreadable:
            raise FileNotFoundError(sha)
        return real(sha)

    monkeypatch.setattr(store, "open", opening)
    after = ""
    sent = 0
    for _ in range(40):
        report = sync.send_files(seconds=0.0, after=after)
        sent += report.sent
        if not report.stopped:
            break
        after = report.resume_after
    assert sent == 3
