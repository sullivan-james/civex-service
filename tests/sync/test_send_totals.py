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
