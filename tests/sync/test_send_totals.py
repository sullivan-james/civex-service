"""Sending files shows one absolute total from the start: the files, and their
bytes, still unconfirmed, counted from the inventory in one query. It does not
grow as slices are asked about, and a pass asks only about the slice it is on."""

from __future__ import annotations

from civex.domain.sync import SENDING


def _many_files(ctx, record, n: int) -> list[bytes]:
    """`n` records, each citing its own file."""
    ctx.schema_svc.add_field("encounter", "scan", "file")
    ctx.commit()
    contents = [f"scan number {i}".encode() * (i + 1) for i in range(n)]
    for i, content in enumerate(contents):
        target = record
        if i:
            target = ctx.record_svc.add(
                "study", "encounter", {"site": f"s{i}", "depth": 1.0}
            )
        ref = ctx.file_svc.store_bytes(content, f"scan{i}.bin")
        ctx.record_svc.update(
            str(target.id),
            {"site": f"s{i}", "depth": 1.0, "scan": ref.to_dict()},
        )
    ctx.commit()
    return contents


def test_totals_are_known_at_once_and_do_not_grow(pair, monkeypatch):
    from civex.services import sync_service

    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 2)
    laptop, _, record = pair
    contents = _many_files(laptop, record, 7)
    laptop.sync_svc.sync()
    size = sum(map(len, contents))
    assert laptop.sync_repo.unconfirmed_totals() == (7, size)

    calls = laptop._holder["inner"].calls
    calls.clear()
    files_before = bytes_before = 0
    after, totals, asks = "", set(), []
    for _ in range(20):
        seen = []
        before = len(calls)
        report = laptop.sync_svc.send_files(
            seconds=0, progress=seen.append, after=after
        )
        asks.append(calls[before:].count("missing_files"))
        sending = [p for p in seen if p.phase == SENDING]
        assert sending[0].done == 0  # the total is there before the first file
        totals |= {
            (files_before + p.total, bytes_before + p.bytes_total) for p in sending
        }
        files_before += sending[-1].done
        bytes_before += sending[-1].bytes_done
        if not report.stopped:
            break
        after = report.resume_after
    assert totals == {(7, size)}
    assert (files_before, bytes_before) == (7, size)
    assert sum(asks) <= 7  # each file asked about once, not once per pass
    assert laptop.sync_repo.unconfirmed_totals() == (0, 0)


def test_files_the_server_already_has_count_as_done(pair):
    laptop, _, record = pair
    contents = _many_files(laptop, record, 3)
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    laptop.sync_repo.forget_numbers()  # a fresh start: it must ask again
    seen = []
    laptop.sync_svc.send_files(progress=seen.append)
    assert seen[0].total == 3 and seen[0].done == 0
    assert (seen[-1].done, seen[-1].total) == (3, 3)
    assert seen[-1].bytes_done == seen[-1].bytes_total == sum(map(len, contents))


def _shas(ctx) -> list[str]:
    return sorted(ctx.sync_repo.referenced_shas("", 100))


def test_a_file_the_server_lost_is_found_on_an_everything_pass(pair, authority):
    laptop, _, record = pair
    _many_files(laptop, record, 3)
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    assert laptop.sync_repo.unconfirmed_totals() == (0, 0)

    authority.file_svc._store.delete(_shas(laptop)[0])  # the server loses one
    authority.commit()

    seen = []
    report = laptop.sync_svc.send_files(everything=True, progress=seen.append)
    assert report.sent == 1
    last = [p for p in seen if p.phase == SENDING][-1]
    assert (last.done, last.total) == (1, 1)  # the total grew by the lost one
    assert last.bytes_done == last.bytes_total > 0


def test_an_unreadable_file_is_owed_not_counted_as_sent(pair):
    laptop, _, record = pair
    _many_files(laptop, record, 3)
    laptop.sync_svc.sync()
    lost = _shas(laptop)[0]
    laptop.file_svc.local_path(lost).unlink()  # its drive isn't plugged in

    seen = []
    report = laptop.sync_svc.send_files(progress=seen.append)
    last = [p for p in seen if p.phase == SENDING][-1]
    assert report.owed == [lost] and report.sent == 2
    assert (last.done, last.owed, last.total) == (2, 1, 3)
    assert last.bytes_done == last.bytes_total  # of what can be read here


def test_a_pass_stopped_mid_slice_resumes_without_repeating(pair, monkeypatch):
    from civex.services import sync_service

    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 3)
    laptop, _, record = pair
    _many_files(laptop, record, 7)
    laptop.sync_svc.sync()
    inner = laptop._holder["inner"]
    uploads: list[str] = []
    real = inner.upload_file

    def counted(sha, *args, **kwargs):
        uploads.append(sha)
        return real(sha, *args, **kwargs)

    inner.upload_file = counted
    after = ""
    for _ in range(20):
        report = laptop.sync_svc.send_files(seconds=0, after=after)
        if not report.stopped:
            break
        after = report.resume_after
    assert sorted(uploads) == _shas(laptop)  # each once, none skipped
    assert laptop.sync_repo.unconfirmed_totals() == (0, 0)


def test_a_stop_request_ends_a_pass_between_slices(pair, monkeypatch):
    from civex.services import sync_service

    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 2)
    laptop, _, record = pair
    _many_files(laptop, record, 6)
    laptop.sync_svc.sync()
    report = laptop.sync_svc.send_files(should_stop=lambda: True)
    assert report.stopped and report.sent == 0


def test_totals_count_only_copies_on_configured_volumes(pair):
    laptop, _, record = pair
    contents = _many_files(laptop, record, 2)
    names = laptop.file_svc._store.volume_names()
    assert laptop.sync_repo.unconfirmed_totals("", names) == (
        2,
        sum(map(len, contents)),
    )
    assert laptop.sync_repo.unconfirmed_totals("", ["gone"]) == (2, 0)


def test_the_run_carries_files_owed_and_bytes_from_pass_to_pass():
    from civex.domain.sync import SyncProgress
    from civex.services.sync_worker import _SendRun

    run = _SendRun()
    run.last = SyncProgress(SENDING, 4, 10, bytes_done=40, bytes_total=100, owed=1)
    run.close_pass()
    # The next pass counts what is left after the cursor: 5 files, 1 unreadable.
    got = run.carried(
        SyncProgress(SENDING, 2, 5, bytes_done=20, bytes_total=50, owed=1), 1.0
    )
    assert (got.done, got.owed, got.total) == (6, 2, 10)
    assert (got.bytes_done, got.bytes_total) == (60, 90)
