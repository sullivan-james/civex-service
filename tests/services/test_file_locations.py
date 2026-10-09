"""Where a record's files are stored: the `location` on file values, what the
file-info lookup reports, and the guarantees around it (one batch lookup, never
persisted, never in the audit log)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import event

from civex.context import AppContext


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def docs(ctx: AppContext, make_schema, make_collection):
    """A collection `study` of `doc` records with a file and a file list."""
    make_schema("doc", fields=[("scan", "file"), ("extras", "file_list")])
    return make_collection("study")


def _record(ctx: AppContext, make_record, **data):
    return make_record("study", "doc", data)


def test_a_file_says_which_volume_it_is_on(ctx: AppContext, docs, make_record) -> None:
    ref = ctx.file_svc.store_bytes(b"scan bytes", "scan.png")
    record = _record(ctx, make_record, scan=ref.to_dict())

    value = ctx.record_svc.get(str(record.id)).data["scan"]

    assert value["location"] == {
        "volume": "default",
        "state": "online",
        "available": True,
        "reason": "",
        "fix": "",
    }


def test_each_file_in_a_list_is_located(
    ctx: AppContext, docs, make_record, tmp_path: Path
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    ctx.store_svc.set_placement(str(docs.id), "archive")
    first = ctx.file_svc.store_bytes(b"one", "1.txt")  # general queue: default
    second = ctx.file_svc.store_bytes(b"two", "2.txt", str(docs.id))  # homed: archive
    record = _record(ctx, make_record, extras=[first.to_dict(), second.to_dict()])

    values = ctx.record_svc.get(str(record.id)).data["extras"]

    assert [v["location"]["volume"] for v in values] == ["default", "archive"]


def test_a_file_on_an_unplugged_volume_is_flagged_unavailable(
    ctx: AppContext, docs, make_record, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "archive")
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(docs.id), "archive")
    ref = ctx.file_svc.store_bytes(b"on the drive", "a.txt", str(docs.id))
    record = _record(ctx, make_record, scan=ref.to_dict())
    drive.rename(drive.with_name("archive-unplugged"))

    location = ctx.record_svc.get(str(record.id)).data["scan"]["location"]

    assert location["volume"] == "archive" and location["state"] == "offline"
    assert location["available"] is False
    # It says why and what to do, so the record page can tell a person which
    # drive to plug in without sending them to Settings first.
    assert location["reason"] and location["fix"]
    assert "archive" in location["reason"] + location["fix"]


def test_a_file_that_is_nowhere_is_unknown_not_missing(
    ctx: AppContext, docs, make_record
) -> None:
    ghost = {"sha256": "ab" * 32, "filename": "ghost.bin", "size": 3}
    record = _record(ctx, make_record, scan=ghost)

    location = ctx.record_svc.get(str(record.id)).data["scan"]["location"]

    assert location == {
        "volume": None,
        "state": "unknown",
        "available": None,
        "reason": "",
        "fix": "",
    }


def test_only_file_fields_are_decorated(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("plain", fields=[("title", "string"), ("scan", "file")])
    make_collection("c")
    ref = ctx.file_svc.store_bytes(b"x", "x.txt")
    record = make_record("c", "plain", {"title": "hello", "scan": ref.to_dict()})

    data = ctx.record_svc.get(str(record.id)).data

    assert data["title"] == "hello"
    assert "location" in data["scan"]


def test_a_batch_of_records_costs_one_location_lookup(
    ctx: AppContext, docs, make_record
) -> None:
    for i in range(12):
        ref = ctx.file_svc.store_bytes(f"file {i}".encode(), f"{i}.txt")
        _record(ctx, make_record, scan=ref.to_dict())
    ctx.commit()
    lookups: list[str] = []
    engine = ctx._session.get_bind()

    def count(conn, cursor, statement, *rest):
        # Where each record's file is: the copy it points at (file_references),
        # or, for one it doesn't point at yet, the inventory.
        if "stored_objects" in statement or "FROM file_references" in statement:
            lookups.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        records = ctx.record_svc.find_by_schema("doc", limit=50)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    located = [r.data["scan"]["location"]["volume"] for r in records]
    assert located == ["default"] * 12
    assert len(lookups) == 1  # not one per record, and not one per file


def test_the_location_is_never_stored_even_if_a_client_sends_it_back(
    ctx: AppContext, docs, make_record
) -> None:
    ref = ctx.file_svc.store_bytes(b"scan", "scan.png")
    record = _record(ctx, make_record, scan=ref.to_dict())
    echoed = ctx.record_svc.get(str(record.id)).data  # what the UI holds, with location

    ctx.record_svc.update(str(record.id), echoed)
    ctx.commit()

    stored = ctx.record_svc._records.get_by_prefix(str(record.id))
    assert "location" not in json.dumps(stored.data)
    assert "resolved_filename" not in json.dumps(stored.data)
    assert (
        ctx.record_svc.get(str(record.id)).data["scan"]["location"]["volume"]
        == "default"
    )


def test_the_location_never_reaches_the_audit_log(
    ctx: AppContext, docs, make_record
) -> None:
    ref = ctx.file_svc.store_bytes(b"scan", "scan.png")
    record = _record(ctx, make_record, scan=ref.to_dict())
    ctx.record_svc.update(str(record.id), {"scan": ref.to_dict()})
    ctx.commit()

    entries = ctx.audit_svc.list_audit(entity_id=record.id)

    assert entries
    assert all("location" not in json.dumps(e.new_data or {}) for e in entries)
    assert all("location" not in json.dumps(e.old_data or {}) for e in entries)


# -- the file-info lookup -----------------------------------------------------


def test_file_info_lists_copies_size_and_everything_using_it(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("doc", fields=[("scan", "file")])
    make_collection("a")
    make_collection("b")
    ref = ctx.file_svc.store_bytes(b"shared content", "shared.txt")
    make_record("a", "doc", {"scan": ref.to_dict()})
    make_record("a", "doc", {"scan": ref.to_dict()})
    make_record("b", "doc", {"scan": ref.to_dict()})
    ctx.commit()

    info = ctx.file_info_svc.info(ref.sha256)

    assert info.size == len(b"shared content")
    assert [(c.volume, c.present, c.state) for c in info.copies] == [
        ("default", True, "online")
    ]
    assert Path(info.copies[0].path).parts[-2:] == (ref.sha256[:2], ref.sha256[2:])
    assert info.records == 3
    assert [(c.name, c.records) for c in info.collections] == [("a", 2), ("b", 1)]


def test_file_info_still_accounts_for_a_file_on_an_unplugged_drive(
    ctx: AppContext, docs, make_record, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "archive")
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(docs.id), "archive")
    ref = ctx.file_svc.store_bytes(b"on the drive", "a.txt", str(docs.id))
    _record(ctx, make_record, scan=ref.to_dict())
    ctx.commit()
    drive.rename(drive.with_name("archive-unplugged"))

    info = ctx.file_info_svc.info(ref.sha256)

    [copy] = info.copies
    assert (copy.volume, copy.present, copy.state) == ("archive", None, "offline")


def test_file_info_for_something_unknown(ctx: AppContext) -> None:
    from civex.domain.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        ctx.file_info_svc.info("cd" * 32)


def test_offline_location_tells_unplugged_from_missing(
    ctx: AppContext, docs, tmp_path: Path
) -> None:
    drive = _drive(tmp_path, "archive")
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(docs.id), "archive")
    ref = ctx.file_svc.store_bytes(b"on the drive", "a.txt", str(docs.id))
    drive.rename(drive.with_name("archive-unplugged"))

    volume, status = ctx.file_svc.offline_location(ref.sha256)

    assert volume == "archive" and status.state == "offline"
    assert ctx.file_svc.offline_location("ef" * 32) is None


def test_workflows_see_a_files_identity_not_where_it_is_stored(
    ctx: AppContext, docs, make_record
) -> None:
    from civex.plugins.base import WorkflowContext

    ref = ctx.file_svc.store_bytes(b"scan", "scan.png")
    record = _record(ctx, make_record, scan=ref.to_dict(), extras=[ref.to_dict()])
    located = ctx.record_svc.get(str(record.id))
    assert "location" in located.data["scan"]  # what the API returns

    wf = WorkflowContext(
        record=located, dataset=ctx.dataset_svc.get("study"), _app_ctx=ctx
    )

    for value in (wf.record.data["scan"], wf.record.data["extras"][0]):
        assert "location" not in value
        assert value["sha256"] == ref.sha256 and "resolved_filename" in value
    assert "location" in located.data["scan"]  # the caller's record is untouched
