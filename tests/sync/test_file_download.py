"""A device gets the files other devices add: in the background, when one is
opened or exported, or all at once from the CLI; and says where one is
meanwhile."""

from __future__ import annotations

import os

from civex.config import load_config
from civex.domain.file_access import FileSelection
from civex.domain.query import RecordQuery


def data(ctx, record):
    return ctx.record_svc.get(str(record.id)).data


def _with_file(laptop, record, content: bytes):
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    ref = laptop.file_svc.store_bytes(content, "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    return ref


def _location(ctx, record):
    return ctx.record_svc.get(str(record.id)).data["scan"]["location"]


def test_a_file_another_device_added_is_on_the_server_until_fetched(pair):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"the scan")
    phone.sync_svc.sync()

    assert data(phone, record)["scan"]["sha256"] == ref.sha256
    assert not phone.file_svc.exists(ref.sha256)
    assert _location(phone, record)["state"] == "remote"
    assert phone.sync_svc.files_to_fetch() == 1
    assert phone.sync_svc.status().files_to_fetch == 1

    done: list[int] = []
    report = phone.sync_svc.fetch_files(progress=done.append)
    phone.commit()

    assert (report.fetched, report.absent, done) == (1, [], [1])
    assert phone.file_svc.retrieve(ref.sha256) == b"the scan"
    assert _location(phone, record)["state"] == "online"
    assert phone.sync_svc.files_to_fetch() == 0


def test_a_file_the_server_has_not_got_yet_is_left_for_later(pair, authority):
    laptop, phone, record = pair
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    laptop.sync_svc.sync()
    ref = laptop.file_svc.store_bytes(b"not sent", "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.file_svc.object_path(ref.sha256).unlink()  # its drive is unplugged
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    report = phone.sync_svc.fetch_files()
    assert (report.fetched, report.absent) == (0, [ref.sha256])
    assert phone.sync_svc.fetch_file(ref.sha256) is False


def test_opening_one_fetches_it(pair):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"opened")
    phone.sync_svc.sync()
    assert phone.sync_svc.fetch_file(ref.sha256) is True
    assert phone.file_svc.retrieve(ref.sha256) == b"opened"
    assert phone.sync_svc.fetch_file(ref.sha256) is True  # already here


def test_an_export_fetches_what_is_on_the_server_first(pair):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"exported")
    phone.sync_svc.sync()
    selection = FileSelection(query=RecordQuery(dataset="study"))

    looked = phone.file_access_svc.plan(selection)  # a preview fetches nothing
    assert [i.state for i in looked.items] == ["remote"]
    assert not phone.file_svc.exists(ref.sha256)

    plan = phone.file_access_svc.plan(selection, fetch=True)
    assert [i.available for i in plan.items] == [True]
    assert plan.complete


def test_which_files_a_device_keeps_is_saved_in_its_settings(pair):
    _, phone, _ = pair
    phone.sync_svc.set_download_files("opened")
    root = phone.sync_svc._config.project_root
    previous = os.getcwd()
    os.chdir(root)
    try:
        assert load_config().sync.download_files == "opened"
    finally:
        os.chdir(previous)
    assert phone.sync_svc.status().download_files == "opened"


def test_an_authority_fetches_from_nobody(authority):
    assert authority.sync_svc.files_to_fetch() == 0
    assert authority.sync_svc.fetch_files().attempted == 0


def test_a_preview_counts_files_to_download_and_the_export_says_it_is_downloading(
    pair,
):
    from civex.services.progress import registry

    laptop, phone, record = pair
    _with_file(laptop, record, b"to fetch")
    phone.sync_svc.sync()
    selection = FileSelection(query=RecordQuery(dataset="study"))

    preview = phone.file_access_svc.plan(selection)
    assert preview.complete  # downloading it first is part of the export
    assert preview.to_dict()["to_fetch"] == {"files": 1, "bytes": len(b"to fetch")}
    assert preview.unavailable == []

    progress = registry.start("p-download-test")
    phases = []
    real_phase = progress.phase
    progress.phase = lambda label, total=0: (
        phases.append(label),
        real_phase(label, total),
    )  # type: ignore[method-assign]
    plan = phone.file_access_svc.plan(selection, progress=progress, fetch=True)
    assert plan.complete and plan.available == 1
    assert "Downloading 1 file from the server" in phases


def test_a_file_the_server_lacks_is_unreachable_once_the_export_has_tried(
    pair, authority
):
    laptop, phone, record = pair
    ref = _with_file(laptop, record, b"never sent")
    authority.file_svc._store.delete(ref.sha256)
    authority.commit()
    phone.sync_svc.sync()
    selection = FileSelection(query=RecordQuery(dataset="study"))

    plan = phone.file_access_svc.plan(selection, fetch=True)
    assert not plan.complete
    (group,) = plan.unavailable
    # Where it still is: the device that added it (its token's name).
    assert group.reason == "It is still only on 'laptop'."
    assert group.fix == "It arrives here once that computer syncs."
