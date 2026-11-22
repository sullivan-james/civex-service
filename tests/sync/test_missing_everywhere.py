"""A file the server said it hasn't got is "missing everywhere": remembered in
the project, asked for again only on a backoff (so not on every worker start),
left out of what is downloading, and hidden by ignoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from civex.db.models import ServerLack
from civex.repositories.local.sync_repo import LACK_RETRY_MAX, lack_wait


def _cite_unsent(laptop, record, content: bytes = b"nobody has this"):
    """A record citing a file the server never got (the bytes stay on the
    laptop, which hasn't sent them), seen from a phone that follows the server."""
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(content, "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    return ref


def _due_now(ctx, sha: str) -> None:
    ctx.sync_repo._s.execute(
        update(ServerLack)
        .where(ServerLack.sha256 == sha)
        .values(retry_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    ctx.commit()


def test_the_wait_doubles_up_to_a_day():
    assert lack_wait(1) == timedelta(minutes=10)
    assert lack_wait(2) == timedelta(minutes=20)
    assert lack_wait(3) == timedelta(minutes=40)
    assert lack_wait(50) == LACK_RETRY_MAX


def test_an_absent_file_is_not_asked_for_again_before_its_wait(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record)
    phone.sync_svc.sync()
    assert phone.sync_svc.files_to_fetch() == 1
    assert phone.sync_svc.files_to_try() == 1

    first = phone.sync_svc.fetch_files()
    assert (first.attempted, first.absent) == (1, [ref.sha256])

    # Remembered in the database, so a worker that starts afresh (an empty
    # in-memory set) still doesn't ask.
    phone.sync_repo._s.expire_all()
    assert phone.sync_svc.files_to_try() == 0
    assert phone.sync_svc.fetch_files().attempted == 0


def test_the_wait_grows_each_time_the_server_says_no(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record)
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    _due_now(phone, ref.sha256)

    assert phone.sync_svc.fetch_files().absent == [ref.sha256]
    row = phone.sync_repo._s.get(ServerLack, ref.sha256)
    assert row.misses == 2
    assert row.retry_at - row.asked_at == timedelta(minutes=20)


def test_a_file_that_reaches_the_server_later_is_fetched(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record, b"comes later")
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    assert phone.sync_svc.files_to_try() == 0

    laptop.sync_svc.send_files()  # the other computer uploads it
    _due_now(phone, ref.sha256)  # its wait is over

    assert phone.sync_svc.files_to_try() == 1
    assert phone.sync_svc.fetch_files().fetched == 1
    assert phone.file_svc.retrieve(ref.sha256) == b"comes later"
    assert phone.sync_svc.files_missing() == 0
    assert phone.sync_repo.server_lacks_of({ref.sha256}) == set()


def test_a_change_to_a_record_citing_it_asks_again_at_once(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record, b"seen in the feed")
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    assert phone.sync_svc.files_to_try() == 0

    laptop.sync_svc.send_files()
    laptop.record_svc.update(
        str(record.id), {"site": "y", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()  # no waiting: the feed showed the record change

    assert phone.sync_svc.files_to_try() == 1
    assert phone.sync_svc.fetch_files().fetched == 1


def test_counts_and_status_separate_missing_from_downloading(pair):
    laptop, phone, record = pair
    _cite_unsent(laptop, record)
    phone.sync_svc.sync()
    assert phone.sync_svc.status().files_to_fetch == 1
    assert phone.sync_svc.status().files_missing == 0

    phone.sync_svc.fetch_files()
    status = phone.sync_svc.status()
    assert (status.files_to_fetch, status.files_missing) == (0, 1)


def test_ignoring_hides_it_from_every_count(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record)
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    assert phone.sync_svc.ignore_missing([ref.sha256]) == 1

    status = phone.sync_svc.status()
    assert (status.files_to_fetch, status.files_missing) == (0, 0)
    assert status.files_ignored == 1


def test_ignoring_a_file_never_asked_about_leaves_the_download_count(pair):
    laptop, phone, record = pair
    ref = _cite_unsent(laptop, record)
    phone.sync_svc.sync()
    assert phone.sync_svc.files_to_fetch() == 1  # not asked about yet

    phone.sync_svc.ignore_missing([ref.sha256])  # asks the server, which lacks it
    assert phone.sync_svc.files_to_fetch() == 0
