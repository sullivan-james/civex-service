"""Which collections' files a device keeps, what is here and what is only on
the server, and freeing space by removing copies the server holds."""

from __future__ import annotations

from civex.domain.exceptions import ValidationError


def _with_file(laptop, record, content: bytes, field: str = "scan"):
    laptop.schema_svc.add_field("encounter", field, "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(content, f"{field}.bin")
    data = laptop.record_svc.get(str(record.id)).data
    laptop.record_svc.update(str(record.id), {**_plain(data), field: ref.to_dict()})
    laptop.commit()
    laptop.sync_svc.sync()
    return ref


def _plain(data):
    return {k: v for k, v in data.items() if not isinstance(v, dict)}


def _row(ctx, name="study"):
    return next(r for r in ctx.sync_svc.collection_files() if r.name == name)


def test_the_report_says_what_is_here_and_what_is_only_on_the_server(pair):
    laptop, phone, record = pair
    _with_file(laptop, record, b"twelve bytes")
    phone.sync_svc.sync()

    row = _row(phone)
    assert (row.mode, row.chosen) == ("keep", False)
    assert (row.files_here, row.files_on_server) == (0, 1)
    phone.sync_svc.fetch_files()
    phone.commit()
    row = _row(phone)
    assert (row.files_here, row.bytes_here, row.files_on_server) == (1, 12, 0)


def test_a_collection_fetched_when_opened_is_not_downloaded_in_the_background(pair):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"later")
    phone.sync_svc.sync()

    assert phone.sync_svc.set_collection_mode("study", "opened") == "opened"
    assert phone.sync_svc.files_to_fetch() == 0
    assert phone.sync_svc.fetch_files().fetched == 0
    assert phone.sync_svc.fetch_file(ref.sha256)  # opening it still works

    phone.sync_svc.set_download_files("opened")  # the default
    assert phone.sync_svc.set_collection_mode("study", None) == "opened"
    assert phone.sync_svc.set_collection_mode("study", "keep") == "keep"
    assert _row(phone).chosen


def test_freeing_space_removes_copies_the_server_holds(pair):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"big recording")
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    phone.commit()

    counted = phone.sync_svc.free_up("study")
    assert (counted.files, counted.bytes) == (1, len(b"big recording"))
    assert phone.file_svc.exists(ref.sha256)  # counting removes nothing

    done = phone.sync_svc.free_up("study", dry_run=False)
    assert done.files == 1
    assert not phone.file_svc.exists(ref.sha256)
    assert _row(phone).mode == "opened"  # so it isn't fetched straight back
    loc = phone.record_svc.get(str(record.id)).data["scan"]["location"]
    assert loc["state"] == "remote"
    assert phone.sync_svc.fetch_file(ref.sha256)  # and it comes back on demand


def test_a_file_the_server_has_not_got_is_never_removed(pair, authority):
    laptop, _, record = pair
    ref = _with_file(laptop, record, b"only here")
    authority.file_svc._store.delete(ref.sha256)  # say it never arrived
    authority.commit()

    report = laptop.sync_svc.free_up("study", dry_run=False)
    assert (report.files, report.not_on_server) == (0, 1)
    assert laptop.file_svc.exists(ref.sha256)


def test_a_file_a_kept_collection_also_uses_stays(pair):
    laptop, _, record = pair
    ref = _with_file(laptop, record, b"shared")
    laptop.dataset_svc.create("archive")
    laptop.dataset_svc.update("archive", schemas=["encounter"])
    laptop.record_svc.add(
        "archive", "encounter", {"site": "a", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()

    report = laptop.sync_svc.free_up("study", dry_run=False)
    assert (report.files, report.kept_shared) == (0, 1)
    assert laptop.file_svc.exists(ref.sha256)


def test_without_a_server_there_is_nothing_to_free_up_to(authority):
    import pytest

    with pytest.raises(ValidationError, match="nowhere else"):
        authority.sync_svc.free_up("study")


def test_picked_files_are_downloaded_and_freed_by_the_same_rules(pair):
    from civex.domain.file_access import FileSelection
    from civex.domain.query import RecordQuery

    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"picked")
    phone.sync_svc.sync()
    svc = phone.file_access_svc
    everything = FileSelection(query=RecordQuery(dataset="study"))

    _, on_server = svc.chosen(everything, place="server")
    assert [i.sha256 for i in on_server] == [ref.sha256]
    assert svc.download(on_server).fetched == 1
    phone.commit()
    _, here = svc.chosen(everything, place="here")
    assert [i.sha256 for i in here] == [ref.sha256]

    # A kept collection's files aren't freed one by one: the background
    # download would only fetch them back.
    kept = svc.free_up(here, dry_run=False)
    assert (kept.files, kept.kept_shared) == (0, 1)
    assert phone.file_svc.exists(ref.sha256)

    phone.sync_svc.set_collection_mode("study", "opened")
    freed = svc.free_up(here, dry_run=False)
    assert freed.files == 1 and not phone.file_svc.exists(ref.sha256)


def test_moving_a_file_only_on_the_server_downloads_it_onto_that_drive(pair, tmp_path):
    """It goes straight there (not to its collection's drive and then moved),
    and that is the whole move."""
    from civex.domain.file_access import FileSelection
    from civex.domain.query import RecordQuery

    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"to the archive")
    phone.sync_svc.sync()
    drive = tmp_path / "archive-drive"
    drive.mkdir()
    phone.store_svc.add_volume("archive", str(drive))
    phone.commit()
    svc = phone.file_access_svc
    _, items = svc.chosen(FileSelection(query=RecordQuery(dataset="study")))

    shas, downloaded = svc.to_move(items, "archive")
    phone.commit()

    assert (shas, downloaded) == ([], 1)
    assert phone.file_svc._store.locate_volumes([ref.sha256]) == {ref.sha256: "archive"}
